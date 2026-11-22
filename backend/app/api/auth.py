"""Student SMS OTP authentication and profile endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import extract_user_token, get_optional_student, require_student
from app.core.config import get_settings
from app.db.session import get_session
from app.models.auth import OtpCode, User, UserSession
from app.services.account_service import get_user_storage_quota_bytes
from app.services.auth_billing_service import (
    USER_COOKIE_NAME,
    apply_plan_to_user,
    create_user_session_token,
    get_or_init_billing_settings,
    get_user_today_tokens,
    hash_otp_code,
    hash_phone_verification_token,
    normalize_iranian_phone,
    parse_user_session_token,
    serialize_user,
    verify_otp_hash,
)
from app.services.passwords import hash_password, verify_password
from app.services.sms_provider import get_sms_provider
from app.core.client_ip import client_ip
from app.services.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RequestOtpBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)


class VerifyOtpBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    code: str = Field(min_length=4, max_length=10)
    full_name: str | None = Field(default=None, max_length=120)


class UpdateProfileBody(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)


class PasswordLoginBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    password: str = Field(min_length=1, max_length=128)


class CompleteRegistrationBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    verification_token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=12, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class PasswordChangeBody(BaseModel):
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def _is_https(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


OTP_REQUEST_IP_LIMIT = 20
OTP_REQUEST_IP_WINDOW_SECONDS = 3600
OTP_VERIFY_IP_LIMIT = 30
OTP_VERIFY_IP_WINDOW_SECONDS = 900


def _is_ascii_digits(value: str, length: int) -> bool:
    return len(value) == length and value.isascii() and value.isdigit()


async def _enforce_ip_limit(request: Request, *, bucket: str, limit: int, window: int) -> None:
    decision = await check_rate_limit(
        identity=f"{bucket}:{client_ip(request)}",
        bucket=bucket,
        limit=limit,
        window_seconds=window,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="تعداد درخواست‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


async def _create_user_session_response(
    *,
    user: User,
    request: Request,
    response: Response,
    session: AsyncSession,
    now: datetime,
    is_new_user: bool = False,
) -> dict[str, object]:
    """Create a revocable DB-backed user session and return the normal account payload."""
    settings = get_settings()
    billing = await get_or_init_billing_settings(session)
    user.last_login_at = now
    user.deleted_at = None
    await session.flush()

    token_nonce = secrets.token_hex(12)
    token = create_user_session_token(user.id, nonce=token_nonce)
    user_agent = (request.headers.get("user-agent") or "")[:512] or None
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    ip_address = (forwarded_for or (request.client.host if request.client else ""))[:64] or None
    session.add(
        UserSession(
            user_id=user.id,
            token_nonce=token_nonce,
            user_agent=user_agent,
            ip_address=ip_address,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.user_session_ttl_seconds),
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(user)

    https = _is_https(request)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=token,
        max_age=settings.user_session_ttl_seconds,
        httponly=True,
        samesite="none" if https else "lax",
        secure=https,
        path="/",
    )
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "authenticated": True,
        "is_new_user": is_new_user,
        "token": token,
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
            now=now,
        ),
    }


PASSWORD_LOGIN_IP_LIMIT = 30
PASSWORD_LOGIN_ACCOUNT_LIMIT = 8
PASSWORD_LOGIN_WINDOW_SECONDS = 900


async def _enforce_password_login_limits(request: Request, phone: str) -> None:
    await _enforce_ip_limit(
        request,
        bucket="password_login_ip",
        limit=PASSWORD_LOGIN_IP_LIMIT,
        window=PASSWORD_LOGIN_WINDOW_SECONDS,
    )
    decision = await check_rate_limit(
        identity=f"password_login_phone:{phone}",
        bucket="password_login_phone",
        limit=PASSWORD_LOGIN_ACCOUNT_LIMIT,
        window_seconds=PASSWORD_LOGIN_WINDOW_SECONDS,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="تعداد تلاش‌های ورود برای این شماره بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


@router.post("/request-otp")
async def request_otp(
    body: RequestOtpBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await _enforce_ip_limit(
        request, bucket="otp_request", limit=OTP_REQUEST_IP_LIMIT, window=OTP_REQUEST_IP_WINDOW_SECONDS
    )
    try:
        phone = normalize_iranian_phone(body.phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    settings = get_settings()
    now = datetime.now(timezone.utc)

    latest = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == phone)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if latest is not None and settings.otp_resend_seconds > 0:
        elapsed = (now - _utc(latest.created_at)).total_seconds()
        if elapsed < settings.otp_resend_seconds and latest.consumed_at is None:
            wait_s = max(1, int(settings.otp_resend_seconds - elapsed))
            raise HTTPException(
                status_code=429,
                detail=f"لطفاً {wait_s} ثانیه دیگر برای ارسال مجدد کد صبر کنید.",
            )

    # Invalidate earlier unconsumed OTP codes for this number.
    await session.execute(
        update(OtpCode)
        .where(OtpCode.phone_number == phone, OtpCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    code = f"{secrets.randbelow(900000) + 100000}"
    otp_id = str(uuid4())
    otp = OtpCode(
        id=otp_id,
        phone_number=phone,
        code_hash=hash_otp_code(otp_id, phone, code),
        attempts=0,
        max_attempts=settings.otp_max_attempts,
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        created_at=now,
    )
    session.add(otp)
    await session.commit()

    provider = get_sms_provider(settings)
    try:
        delivery = await provider.send_otp(phone_number=phone, code=code)
    except Exception as error:  # noqa: BLE001
        logger.exception("SMS OTP delivery failed via %s", provider.provider_name)
        raise HTTPException(
            status_code=503,
            detail="ارسال پیامک در حال حاضر با خطا مواجه شد. لطفاً لحظاتی دیگر تلاش کنید.",
        ) from error

    payload: dict[str, object] = {
        "sent": True,
        "phone_number": phone,
        "provider": delivery.provider,
        "expires_in_seconds": settings.otp_ttl_seconds,
        "resend_after_seconds": settings.otp_resend_seconds,
    }
    if settings.demo_mode:
        payload["demo_code"] = code
    return payload


@router.post("/verify-otp")
async def verify_otp(
    body: VerifyOtpBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        phone = normalize_iranian_phone(body.phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    await _enforce_ip_limit(
        request, bucket="otp_verify", limit=OTP_VERIFY_IP_LIMIT, window=OTP_VERIFY_IP_WINDOW_SECONDS
    )
    code_clean = body.code.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if not _is_ascii_digits(code_clean, 6):
        raise HTTPException(status_code=422, detail="کد تأیید باید ۶ رقم باشد.")

    now = datetime.now(timezone.utc)
    # Lock the active OTP row so parallel verify requests cannot each read the same
    # attempt counter and bypass max_attempts (SELECT ... FOR UPDATE on PostgreSQL).
    otp = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None:
        raise HTTPException(status_code=401, detail="کد فعالی برای این شماره یافت نشد. ابتدا درخواست کد بدهید.")

    if _utc(otp.expires_at) <= now:
        otp.consumed_at = now
    user = await session.scalar(select(User).where(User.phone_number == phone))
    is_new_user = user is None
    if user is not None and (not user.is_active or user.deleted_at is not None):
        await session.commit()
        raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال یا حذف شده است.")

    if user is None or not user.password_hash:
        # OTP was consumed; the high-entropy challenge is bound to this phone and OTP row,
        # expires quickly, and can be redeemed exactly once by complete-registration.
        verification_token = secrets.token_urlsafe(32)
        otp.verified_at = now
        otp.verification_token_hash = hash_phone_verification_token(otp.id, phone, verification_token)
        otp.verification_token_expires_at = now + timedelta(minutes=10)
        await session.commit()
        response.headers["Cache-Control"] = "no-store"
        return {
            "authenticated": False,
            "password_setup_required": True,
            "verification_token": verification_token,
            "phone_number": phone,
            "is_new_user": is_new_user,
        }

    if body.full_name and body.full_name.strip() and not user.full_name:
        user.full_name = body.full_name.strip()
    user.phone_verified_at = user.phone_verified_at or now
    return await _create_user_session_response(
        user=user,
        request=request,
        response=response,
        session=session,
        now=now,
        is_new_user=False,
    )


@router.post("/complete-registration")
async def complete_registration(
    body: CompleteRegistrationBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        phone = normalize_iranian_phone(body.phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    now = datetime.now(timezone.utc)
    otp = await session.scalar(
        select(OtpCode)
        .where(
            OtpCode.phone_number == phone,
            OtpCode.verified_at.is_not(None),
            OtpCode.verification_token_hash.is_not(None),
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None:
        raise HTTPException(status_code=401, detail="تأیید شماره منقضی شده است؛ دوباره کد پیامکی دریافت کنید.")
    token_expiry = _utc(otp.verification_token_expires_at) if otp.verification_token_expires_at else None
    if token_expiry is None or token_expiry <= now:
        otp.verification_token_hash = None
        otp.verification_token_expires_at = None
        await session.commit()
        raise HTTPException(status_code=401, detail="مهلت ثبت رمز پایان یافته است؛ دوباره شماره را تأیید کنید.")

    expected = hash_phone_verification_token(otp.id, phone, body.verification_token)
    if not secrets.compare_digest(expected, otp.verification_token_hash or ""):
        raise HTTPException(status_code=401, detail="مجوز ثبت رمز معتبر نیست.")

    user = await session.scalar(select(User).where(User.phone_number == phone))
    if user is not None and (not user.is_active or user.deleted_at is not None):
        await session.commit()
        raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال یا حذف شده است.")
    if user is not None and user.password_hash:
        otp.verification_token_hash = None
        otp.verification_token_expires_at = None
        await session.commit()
        raise HTTPException(status_code=409, detail="برای این حساب قبلاً رمز ثبت شده است؛ از ورود با رمز استفاده کنید.")

    if user is None:
        billing = await get_or_init_billing_settings(session)
        user = User(
            phone_number=phone,
            full_name=body.full_name.strip() if body.full_name and body.full_name.strip() else None,
            role="student",
            is_active=True,
            phone_verified_at=now,
            password_hash=hash_password(body.password),
            created_at=now,
            updated_at=now,
        )
        apply_plan_to_user(
            user,
            plan_code="trial",
            plan_name="هدیه ثبت‌نام",
            tokens_granted=billing.starter_tokens,
            duration_days=billing.starter_duration_days,
            carry_over_valid=False,
            now=now,
        )
        session.add(user)
    else:
        if body.full_name and body.full_name.strip() and not user.full_name:
            user.full_name = body.full_name.strip()
        user.password_hash = hash_password(body.password)
        user.phone_verified_at = user.phone_verified_at or now

    otp.verification_token_hash = None
    otp.verification_token_expires_at = None
    return await _create_user_session_response(
        user=user,
        request=request,
        response=response,
        session=session,
        now=now,
        is_new_user=user.created_at == now,
    )


@router.post("/login")
async def password_login(
    body: PasswordLoginBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        phone = normalize_iranian_phone(body.phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    await _enforce_password_login_limits(request, phone)
    user = await session.scalar(select(User).where(User.phone_number == phone))
    if (
        user is None
        or not user.is_active
        or user.deleted_at is not None
        or not verify_password(body.password, user.password_hash if user is not None else None)
    ):
        raise HTTPException(status_code=401, detail="شماره موبایل یا رمز عبور نادرست است.")

    return await _create_user_session_response(
        user=user,
        request=request,
        response=response,
        session=session,
        now=datetime.now(timezone.utc),
        is_new_user=False,
    )


@router.put("/me/password")
async def change_password(
    body: PasswordChangeBody,
    request: Request,
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    if user.password_hash and (
        not body.current_password or not verify_password(body.current_password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="رمز فعلی صحیح نیست.")
    user.password_hash = hash_password(body.new_password)
    now = datetime.now(timezone.utc)
    current_nonce = getattr(request.state, "user_session_nonce", None)
    statement = update(UserSession).where(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    )
    if current_nonce:
        statement = statement.where(UserSession.token_nonce != current_nonce)
    await session.execute(statement.values(revoked_at=now))
    await session.commit()
    return {"password_updated": True}




@router.get("/me")
async def get_me(
    response: Response,
    user: User | None = Depends(get_optional_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    if user is None or not user.is_active:
        return {"authenticated": False, "user": None}
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "authenticated": True,
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
        ),
    }


@router.put("/me")
async def update_me(
    body: UpdateProfileBody,
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    user.full_name = body.full_name.strip()[:120]
    await session.commit()
    await session.refresh(user)
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
        )
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    token = extract_user_token(request)
    parsed = parse_user_session_token(token)
    if parsed is not None:
        user_id, nonce, _ = parsed
        session_row = await session.scalar(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.token_nonce == nonce,
                UserSession.revoked_at.is_(None),
            )
        )
        if session_row is not None:
            session_row.revoked_at = datetime.now(timezone.utc)
            await session.commit()

    https = _is_https(request)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=USER_COOKIE_NAME,
        path="/",
        samesite="none" if https else "lax",
        secure=https,
    )
    return {"authenticated": False}
