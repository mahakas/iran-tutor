# گزارش فاز ۰۰ — تثبیت خط مبنا و موجودی واقعی (Baseline & Real Inventory)

> **شاخه:** `arena/b0c11271-iran-tutor` · **کامیت مبنا:** `da1dce7` (merge of PR #34) · **تاریخ:** ۲۰۲۶-۱۱-۲۳
> **دامنه:** فقط مستندسازی؛ هیچ فایل اجرایی/مایگریشنی/تنظیمی تغییر نکرده است.
> **نتیجهٔ کلی: `PASS`** (همهٔ موارد محدودهٔ همین فاز با شواهد اجراشده اثبات شده‌اند؛ شکاف‌ها به‌صراحت در گزارش و ماتریس فهرست شده‌اند.)

---

## ۱) خلاصهٔ دقیق تغییرات و دلیل آن‌ها

| # | مورد | دلیل |
|---|---|---|
| ۱ | ایجاد `docs/REDESIGN_EXECUTION_BASELINE.md` | خروجی مورد انتظار فاز: معماری فعلی، فهرست routeها، مدل‌ها، مایگریشن، قابلیت‌ها، فایل‌های حجیم، تناقض‌های اسناد |
| ۲ | ایجاد `docs/REDESIGN_STATUS_MATRIX.md` | ماتریس وضعیت هر قابلیت با ستون‌های خواسته‌شدهٔ پرامپت فاز |
| ۳ | ایجاد همین گزارش `docs/REDESIGN_PHASE_00_REPORT.md` | دروازهٔ تحویل اجباری فاز |
| ۴ | بازسازی محیط اجرا (`python3 -m venv .venv`، `pip install -r requirements.txt`، `npm install`) | در این checkout فایل‌های محیط وجود نداشتند؛ بدون آن‌ها هیچ تستی قابل اجرا نبود |
| ۵ | تأیید کل زنجیرهٔ `alembic upgrade head` روی PostgreSQL 16.2 (نصب موقت `pgserver`) | الزام فاز: اعمال migration chain روی DB واقعی و reversible بودن آن؛ آثار موقت پس از اجرا حذف شدند |
| ۶ | `git checkout -- frontend/next-env.d.ts` پس از هر build | فایل تولیدشده و تغییرش ناخواسته است (قرارداد پروژه) |

**هیچ کد، تست، مایگریشن یا تنظیمی (.env/production) تغییر/اضافه/حذف نشد.**

---

## ۲) فهرست فایل‌های ایجاد/تغییر یافته و نقش هر فایل

| فایل | نقش | نوع |
|---|---|---|
| `docs/REDESIGN_EXECUTION_BASELINE.md` | مبنای اجرا: راستی‌آزمایی با فرمان‌ها، نمودار معماری، موجودی routeها/مدل‌ها/Alembic/capabilities/skills، فایل‌های حجیم، تناقض اسناد، blockerها | جدید (مستند) |
| `docs/REDESIGN_STATUS_MATRIX.md` | ماتریس وضعیت قابلیت‌ها (auth، ادمین، کتاب/RAG، قابلیت‌های آموزشی، زیرساخت) + پرچم‌های قرمز | جدید (مستند) |
| `docs/REDESIGN_PHASE_00_REPORT.md` | همین گزارش تحویل | جدید (مستند) |

`git status --porcelain` پس از پایان کار، فقط همین سه فایل را نشان می‌دهد.

---

## ۳) قابلیت‌های قبلی که حفظ شدند و تست محافظ آن‌ها

این فاز هیچ چیزی را تغییر نداد، ولی برای اثبات «شکست نخوردن» مبنا، کل مجموعهٔ تست‌ها اجرا شد:

- **Backend — `pytest -q tests`:** 446 passed, 1 skipped (ورود OTP/register/login/recovery، RBAC ۶ نقشی، `require_admin`، CSRF، انتشار/retrieval فیلترها، RAG، آزمون‌ها، فلش‌کارت کامل incl. sessions/CSV/APKG/Explain، Mistake Bank، Mastery، Notebook، Living Book، TTS، Visualize، demo mode، production guard).
- **Frontend — `npm test`:** 41 passed (4 فایل).
- **Build:** `npm run build` exit 0 → همهٔ صفحات قبلی سرجایشان هستند (`/`, `/flashcards`, `/deep-solve`, `/mistakes`, `/mastery`, `/notebook`, `/living-book`, `/study/[bookId]`, `/admin*`, `/account*`).
- **SM-2:** بدون تغییر؛ `test_phase3_flashcards.py` + `test_flashcard_phase4.py` سبز.
- **مایگریشن‌ها:** زنجیرهٔ ۲۳ revision با دستور `upgrade head` روی PostgreSQL 16.2 سبز؛ `c9d0e1f2a3b4` downgrade/re-upgrade تأیید شد.
- **Anki/CSV:** بدون تغییر و با تست پوشش داده شده.

---

## ۴) فرمان‌های دقیق اجراشده و خروجی واقعی

```
# شاخه و وضعیت
git status --short --branch && git log --oneline -3
  → ## arena/b0c11271-iran-tutor @ da1dce7 (working tree در شروع فاز پاک)

# محیط (checkout تازه بود)
cd backend && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cd frontend && npm install

# تست‌های backend
cd backend && ./.venv/bin/python -m pytest -q tests
  → 446 passed, 1 skipped, 1 warning in 128.15s

# توزیع تست‌ها
python -m pytest --collect-only -q | grep -oE 'tests/test_[a-z0-9_]+\.py' | sort | uniq -c | sort -rn
  → مجموع 447 (جدول توزیع در Baseline §2.3)

# تست‌های frontend
cd frontend && npm test
  → Test Files 4 passed (4); Tests 41 passed (41)

# لینت
cd frontend && npm run lint
  → ✖ 14 problems (12 errors, 2 warnings)   # دقیقاً برابر مبنای قبل از تغییر (همه در فایل‌های از‌قبل موجود)

# build
cd frontend && npm run build
  → ✓ Compiled successfully; ✓ Generating static pages (22/22); exit 0
  → M frontend/next-env.d.ts   (تولیدشده → reverted با git checkout)

# Alembic — head
cd backend && ./.venv/bin/alembic heads
  → c9d0e1f2a3b4 (head)   # 23 revision file

# Alembic — کل زنجیره + reversibility روی PostgreSQL 16.2 (نصب موقت pgserver، سپس حذف)
python (pgserver) + alembic upgrade head
  → Running upgrade … → c9d0e1f2a3b4 (تمام زنجیره؛ شامل f3a4b5c6d7e8)
alembic downgrade c9d0e1f2a3b4 → b7c1d2e3f4a5 ; alembic upgrade head
  → ✅ هر دو OK؛ alembic_version = c9d0e1f2a3b4
pip uninstall pgserver (و پاک‌سازی /tmp/pgdata_*)  → آثار موقت حذف شدند
cd backend && ./.venv/bin/alembic upgrade head   # روی SQLite
  → ❌ در f3a4b5c6d7e8 (pre-existing): NotImplementedError (No support for ALTER of constraints in SQLite)

# فهرست routeها (۲۳۹ مسیر) از app.openapi() — در پیوست A مستند شده
```

**اعداد این گزارش من‌غیر‌اجرا و ساختگی نیستند؛ همه از اجرای همین جلسه (2026-11-23، شاخهٔ حاضر) آمده‌اند.**

---

## ۵) تست‌های اجرا‌نشده و دلیل دقیق

| آیتم | دلیل |
|---|---|
| `tests/test_phase4_postgres_smoke.py` (1 skipped) | نیازمند `PHASE4_PG_URL` به یک PostgreSQL اختصاصیِ خالی است و در teardown **همهٔ جداول را drop می‌کند**؛ طبق قوانین پروژه روی DB توسعه/تولید اجرا نشد. معادل واقعی آن در ردیف ۷/۸ بالا با pgserver موقت (خالی) پوشش داده شد. |
| `docker compose up/config` | Docker در این sandbox نصب نیست؛ Compose فقط infra است و تغییر نکرده. |
| بررسی بصری در مرورگر/تلفن واقعی (موبایل، دارک‌مود، KaTeX rendering) | مرورگری (Playwright/Chromium) در این محیط نبود/قابل‌دانلود نبود؛ فقط `npm run build` + jsdom tests + curl-level قابلیت `/flashcards` (از فاز قبل) قابل اتکا است. |
| فراخوانی LLM/STT/Embedding واقعی | کلید/ارائه‌دهندهٔ واقعی در دسترس نیست؛ هیچ ادعایی دربارهٔ کیفیت مدل یا دقت OCR/Transcription واقعی نشده است. |
| تست end-to-end پرداخت واقعی | `PAYMENT_PROVIDER=demo` است؛ درگاه واقعی پیکربندی نشده. |
| اجرای کل زنجیرهٔ Alembic روی SQLite | شکست pre-existing در `f3a4b5c6d7e8` (عدم پشتیبانی SQLite از `ALTER ... DROP CONSTRAINT`) — روی PostgreSQL واقعی انجام و سبز شد. |
| smoke test کیفیت استخراج PDF با مدل واقعی | بدون کلید واقعی امکان‌پذیر نیست. |

---

## ۶) ریسک‌های باقیمانده، تصمیم‌های مالک پروژه و دستور rollback

### ریسک‌ها (از پرتوهای قرمز و Baseline §۱۰)
1. **نقض قاعدهٔ انتشار خودکار کتاب** (ready ولی catalog_status=pending_review ⇒ برای دانش‌آموز نامرئی) — ریشه‌ای‌ترین شکاف محصول/کد.
2. **flashcards/explain از صفحات `needs_review` متن می‌گیرند** — نقض gate RAG.
3. **پوشش تست UI ادمین/دانشجو پایین** (۴ فایل FE test) — بازطراحی UI بدون آن پرخطر است.
4. **`npm run lint`: 14 مشکل از‌قبل موجود** — بودجهٔ فنی‌بدهی تعیین شود.
5. **Ingestion بدون worker/heartbeat/recovery**؛ ری‌استارت پروسه ⇒ jobهای `processing` نیمه‌کاره می‌مانند.
6. **محیط تازهٔ checkout بدون `.venv`/`node_modules`** — برای تضمین تکرارپذیری، مستند/CI لازم است.
7. **اسناد stale** (README، RELEASE_READINESS، PHASE0_INVENTORY) — بخش‌هایی از رفتار امنیتی/RBAC/auth را قدیمی توصیف می‌کنند.
8. **`/podcast` اصلاً وجود ندارد.**

### تصمیم‌های نیازمند مالک پروژه
- تعریف رسمی «انتشار کتاب»: حذف gate `catalog_status` یا معرفی `published_at`؟
- محدودسازی فوری `flashcard_sources` به `PageStatus.done`؟
- سرنوشت پادکست (حذف از نقشه راه یا فاز مستقل).
- استاندارد lint پس از بازطراحی (صفر در فایل‌های جدید؛ بودجهٔ خروج از 14 مشکل قدیمی).
- رویکرد یکپارچهٔ background jobs (BackgroundTasks فعلی یا جدول + reconciler).

### Rollback این فاز
این فاز فقط مستندسازی کرد. برای بازگشت کامل:
```bash
git rm docs/REDESIGN_EXECUTION_BASELINE.md docs/REDESIGN_STATUS_MATRIX.md docs/REDESIGN_PHASE_00_REPORT.md
```
هیچ رفتار محصول، schema، یا داده‌ای تغییر نکرده است.

### شاخهٔ پیشنهادی برای commit (فقط برای اطلاع مالک؛ commit/push انجام نشده)
`docs/redesign-phase-00-baseline` — یا افزودن به همین شاخه با تأیید مالک.

---

## ۷) چک‌لیست تست دستی فارسی (برای بازبینی مالک)

> پیش‌نیاز (در صورت تمایل به دمو): `./scripts/run-live-demo.sh` یا اجرای دستی طبق README.
> ⚠️ دمو فقط برای توسعهٔ محلی است؛ کلید واقعی وارد نکنید.

**الف. احراز هویت**
- [ ] `http://localhost:3000` باز می‌شود؛ ورود با «0912…» + کد نمایشی (در demo نشان داده می‌شود) انجام می‌شود.
- [ ] `/api/v1/auth/me` با cookie `iran_tutor_user` → `authenticated: true`.
- [ ] `/api/v1/admin/...` بدون لاگین → **401**؛ با دانشجو → **403**.
- [ ] logout نشست را revoke می‌کند و cookie پاک می‌شود.
- [ ] POST با `Origin` ناهم‌گون روی یک endpoint mutation → **403 csrf_failed**.

**ب. دانش‌آموز**
- [ ] `/flashcards`: ساخت دک، سه گزینه Fewer/Standard/More، سختی easy/medium/hard، فیلد «می‌خواهی فلش‌کارت‌ها روی چه موضوعی تمرکز کنند؟»، مقصد دک جدید/موجود، پس از ساخت وارد دک ساخته‌شده می‌شود؛ Got/Missed با SM-2 ثبت می‌شود؛ «توضیح بیشتر» با استناد؛ CSV/APKG دانلود می‌شود با UTF-8 BOM.
- [ ] `/flashcards` مطالعه: flip با کلیک و دکمهٔ نمایش پاسخ، «کارت N از ۳۰»، progress، Shuffle (پس از reload ترتیب حفظ می‌شود)، Fullscreen با fallback، پایان → صفحه نتایج + «مرور فقط بلد نبودم».
- [ ] `/study/12` (یا book_id دمو): reader باز می‌شود؛ assist با کتاب پاسخ می‌دهد؛ صفحه‌ها فقط بعد از `done` در جست‌وجو می‌آیند.
- [ ] `/deep-solve`, `/mistakes`, `/mastery`, `/notebook`, `/living-book`: هر کدام mount می‌شوند و دادهٔ واقعی از API می‌گیرند (نه placeholder).
- [ ] آزمون `konkoor` اجرا و کارنامه سمت سرور صادر می‌شود؛ کلید پیش از submission لو نمی‌رود.

**پ. ادمین**
- [ ] `/admin` با `admin/123` (فقط محلی!) باز می‌شود؛ هشدار رمز ضعیف در لاگ دیده می‌شود.
- [ ] `/admin/providers`: CRUD + «تست اتصال» نتیجه را با آudit row نشان می‌دهد؛ کلید در پاسخ API هرگز برنمی‌گردد.
- [ ] `/admin/observability`: audit log فیلترپذیر است؛ drawer جزئیات (prompt/response/citations/tokens) باز می‌شود.
- [ ] `/admin/roles`: تغییر نقش کاربر اعمال می‌شود؛ آخرین super_admin قابل حذف/کاهش رتبه نیست.
- [ ] `/admin/users/[id]`: جزئیات + رمز جدید/جلسات/اعتبار/audit.
- [ ] `/admin` بخش KB: آپلود PDF → job ساخته می‌شود → وضعیت می‌تواند `processing` شود → بعد از اتمام کتاب `ready` می‌شود؛ دکمهٔ «انتشار/تأیید» جداست (یافتهٔ ۱ و ۲ در گزارش مبنا).

**ت. سازگاری دادهٔ واقعی**
- [ ] `/api/v1/curriculum/books?grade_number=12&major_code=math_physics` پس از تأیید کتاب (`/admin → کتاب‌ها → تأیید`) کتاب را برمی‌گرداند؛ قبل از تأیید **برنمی‌گرداند** (رفتار فعلی، مغایر قاعدهٔ محصول — یافتهٔ ۶).
- [ ] فلش‌کارت از فصل یک کتاب با صفحهٔ `needs_review` **متن می‌سازد** (رفتار فعلی، مغایر قاعدهٔ RAG — یافتهٔ ۷).

**ث. زیرساخت**
- [ ] `./scripts/run-live-demo.sh` دو سرویس را بالا می‌آورد؛ `curl :8000/health` → `{"status":"ok","mode":"demo"}`.

---

## ۸) نتیجهٔ صریح

**`PASS`** — همهٔ معیارهای پذیرش همین فاز اثبات شده‌اند:
- هیچ فایل اجرایی/مایگریشنی تغییر نکرده (`git status --porcelain` فقط ۳ فایل docs).
- وضعیت auth، CSRF، RBAC، ادمین (`/admin`، providers، observability، roles، users/[id])، ingestion (BackgroundTasks + kb_ingestion_jobs)، نبود پادکست، central AI gateway (`llm_client` → `ai_gateway` → `capability_runtime`) و قاعدهٔ RAG (`PageStatus.done` در retrieval) **از کد استخراج و ثبت شد**، نه حدس.
- تناقض انتشار خودکار کتاب و استفاده از `needs_review` در flashcards **در کد ثبت شد** (قابل‌اصلاح فقط در فاز بعد).
- همهٔ تست‌ها status واقعی دارند (446/41 سبز؛ 1 skipped با دلیل؛ lint=14 از‌قبل موجود؛ build سبز).
- blockerهای پیش از فاز ۱ فهرست شدند (Baseline §۱۰؛ REPORT §۶).

شرط: این PASS فقط برای **همین فاز (مستندسازی)** است؛ هیچ ادعایی نسبت به رفتار واقعی مدل‌ها، مرورگر واقعی، یا تولید/deployment نمی‌کند.
