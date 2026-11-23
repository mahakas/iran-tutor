# خط مبنای اجرا و موجودی واقعی — فاز ۰۰ بازطراحی Darsyar

> **تاریخ ممیزی:** ۲۰۲۶-۱۱-۲۳ · **شاخه:** `arena/b0c11271-iran-tutor` · **کامیت مبنا:** `da1dce7` (merge of PR #34)
> **دامنه:** فقط مستندسازی؛ هیچ فایل اجرایی/مایگریشنی تغییر/اضافه نشده است (به بخش ۲ توجه کنید).
> **منابع مرجع حقیقت:** کد و تست‌های این checkout؛ اسناد قدیمی‌تر فقط در صورتی که با کد تطابق داشته باشند.

---

## ۱. خلاصهٔ اجرایی مبنا

- پروژه **فعال و قابل‌اجراست**: backend (FastAPI + SQLAlchemy 2 async + Alembic)، frontend (Next.js 16 App Router، RTL). 446 تست pytest سبز (1 skipped)، 41 تست frontend سبز، build فرانت‌اند موفق.
- **مهم‌ترین شکاف با قواعد بازطراحی:** قانون «انتشار خودکار کتاب به‌محض `Book.status == ready`» در کد **پیاده نشده است** — فهرست دانش‌آموز و RAG علاوه بر `ready` به `catalog_status == "approved"` نیاز دارند که فقط با تأیید دستی (`PATCH /api/v1/admin/books/{book_id}/approval`) ست می‌شود (بخش ۹).
- تولید فلش‌کارت از صفحه‌های **`needs_review`** هم متن می‌خواند؛ این با قاعدهٔ «`needs_review`/`failed` هرگز وارد retrieval نشوند» ناسازگار است (بخش ۹).
- **پادکست وجود ندارد**: نه route، نه worker، نه heartbeat/recovery. تنها صدا در محصول «روخوانی صوتی متن انتخاب‌شده (TTS)» است (بخش ۹).
- اسناد README / RELEASE_READINESS / PHASE0_INVENTORY / DARSYAR_AGENT_PACK در چند ادعا قدیمی‌اند (بخش ۹)؛ اعداد این گزارش واقعی و اجرا شده‌اند.

---

## ۲. محیط و فرمان‌های اجرا شده (با خروجی واقعی)

### ۲.۱ وضعیت شروع فاز (مهم)

- در شروع این فاز، `backend/.venv` و `frontend/node_modules` **وجود نداشتند** (شاخه از روی snapshot ساخته شده و وابستگی‌ها محلی‌اند). هر دو بازساخته شدند:
  - `python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`
  - `npm install`
- در حین Build، فایل تولیدشدهٔ `frontend/next-env.d.ts` (`.next/dev/types/*` → `.next/types/*`) تغییر کرد؛ مطابق قرارداد پروژه **به حالت اول برگردانده شد** و PR/COMMIT ای انجام نشد. پایان فاز: `git status --porcelain` فقط سه فایل docs را نشان می‌دهد.
- نسخه‌ها: Python **3.11.2** · Node **v22.22.3** · npm **10.9.8** · Next.js **16.4.6** (Turbopack) · React **19.3.1** · alembic (از venv) — single head `c9d0e1f2a3b4`.

### ۲.۲ جدول baseline (همهٔ فرمان‌ها در ۲۰۲۶-۱۱-۲۳ اجرا شدند)

| # | بررسی | فرمان | نتیجهٔ واقعی |
|---|---|---|---|
| 1 | شاخه و پاکی working tree | `git status --short --branch && git log --oneline -3` | branch `arena/b0c11271-iran-tutor` @ `da1dce7`؛ working tree در شروع فاز پاک بود |
| 2 | تست‌های backend | `cd backend && ./.venv/bin/python -m pytest -q tests` | **446 passed, 1 skipped** in 128.15s (⚠️ 1 warning: `PytestUnhandledThreadExceptionWarning`؛ skipped = `test_phase4_postgres_smoke.py:30`، به‌دلیل نیاز به `PHASE4_PG_URL` و دیتابیس اختصاصی خالی — هرگز روی DB توسعه اجرا نشود) |
| 3 | تست‌های frontend | `cd frontend && npm test` | **41 passed (4 فایل)** in ~8.5s |
| 4 | لینت frontend | `cd frontend && npm run lint` | **14 problems (12 errors, 2 warnings)** — دقیقاً baseline قبل از تغییرات فازهای قبلی است؛ همه در فایل‌های از‌قبل موجود (`StudentApp.tsx`, `ImmersiveReader.tsx`, `MistakeBankWorkspace.tsx`, `ChatRecycleBin.tsx`, `BookGradePicker.tsx`, `AuthFlowModal.tsx`, `AdminUsersPanel.tsx`). فایل‌های جدید این فاز: ۰ مشکل |
| 5 | Build frontend | `cd frontend && npm run build` | ✅ exit 0 — «Compiled successfully»، «Generating static pages (22/22)»؛ مسیرها در بخش ۵.۲ فهرست شده‌اند |
| 6 | Head زنجیره Alembic | `cd backend && ./.venv/bin/alembic heads` | `c9d0e1f2a3b4 (head)`؛ **23 فایل revision** در `alembic/versions/` |
| 7 | کل زنجیره روی PostgreSQL واقعی | نصب موقت `pgserver` 0.1.4 + `alembic upgrade head` | ✅ روی PostgreSQL **16.2** اجرا شد؛ head = `c9d0e1f2a3b4` |
| 8 | reversible بودن مایگریشن جدید | `alembic downgrade c9d0e1f2a3b4 --to b7c1d2e3f4a5` سپس `upgrade head` | ✅ هر دو OK؛ `alembic_version` پس از re-upgrade = `c9d0e1f2a3b4` |
| 9 | تست الکترونیکی زنجیره روی SQLite | `alembic upgrade head` با `DATABASE_URL=sqlite+aiosqlite:///...` | ❌ در `f3a4b5c6d7e8` (pre-existing) با `NotImplementedError: No support for ALTER of constraints in SQLite dialect` متوقف می‌شود. این شکست pre-existing و نامرتبط با این فاز است؛ روی PostgreSQL (ردیف ۷) کل زنجیره سبز است |
| 10 | حذف آثار موقت | `pip uninstall pgserver …`، حذف `/tmp/pgdata_*` | انجام شد؛ مخزن دست‌نخورده ماند |

**هیچ تستی PASS اعلام نمی‌شود مگر خروجی واقعی آن در جدول بالا/پایین آمده باشد.**

### ۲.۳ توزیع تست‌های backend (447 جمع؛ 446 اجرا + 1 skipped)

| تعداد | فایل | تعداد | فایل |
|---:|---|---:|---|
| 43 | test_phase6_rich_study.py | 11 | test_exams.py |
| 39 | test_phase1_d.py | 11 | test_admin_api.py |
| 35 | test_phase2_capabilities_kb.py | 11 | test_curriculum_hotfix.py |
| 33 | test_phase4_memory_rag_streaming.py | 10 | test_phase7_hardening.py |
| 29 | test_phase5_deep_learning.py | 10 | test_security_scope_hardening.py |
| 29 | test_flashcard_phase4.py | 10 | test_retrieval_and_tutor.py |
| 23 | test_phase1_governance.py | 9 | test_curriculum_objective_governance.py |
| 21 | test_user_auth_admin.py | 6 | test_multimodal.py |
| 20 | test_phase3_flashcards.py | 6 | test_admin_control_center.py |
| 14 | test_phase7_followup.py | 4 | test_phase6_auth_plans.py |
| 13 | test_curriculum_api.py | 4 | test_pdf_rendering.py |
| 13 | test_bugfix_hardening.py | 4 | test_demo_mode.py |
| 11 | test_provider_routing_failover.py | 4 | test_account_and_settings.py |
| 2 | test_llm_wrappers.py / test_hybrid_rag.py / test_postgres_lexical.py | 4 | test_book_curriculum_scope.py |
| 2 | test_admin_appearance_and_search.py | 3 | test_tutor_api.py |
| 1 | test_tutor_modes.py / test_phase4_postgres_smoke.py (skip) / test_demo_database.py | | |

---

## ۳. چیدمان مخزن (واقعی)

```
├── .kilocode/rules/architecture.md   # قواعد دائمی (فازها، دامنه درسی ایران، strict source)
├── docker-compose.yml                # postgres:16, qdrant v1.12.4, redis:7 (loopback)
├── .env.example / backend/.env.demo.example
├── backend/
│   ├── app/{core,db,models,services,api}
│   ├── alembic/versions/*            # 23 revision؛ head=c9d0e1f2a3b4
│   ├── scripts/{ingest_book,index_book,test_ingest,test_llm,verify_ai_stack}.py
│   ├── tests/                        # 37 فایل / 447 تست جمع
│   ├── pytest.ini (testpaths=tests, asyncio_mode=auto)
│   └── storage/                      # git-ignored (PDF/تصویر/کش)
├── frontend/
│   ├── app/                          # App Router؛ همه صفحات RTL
│   ├── components/                   # StudentApp, Admin panels, workspaces
│   ├── lib/                          # apiClient, preferences, phase5/6, types…
│   └── tests/                        # AdminUsersPanel, AuthFlowModal, flashcards, apiClient
└── docs/                             # DARSYAR_AGENT_PACK, RELEASE_READINESS, HOTFIX…, PHASE0_INVENTORY…
```

---

## ۴. نمودار معماری فعلی (واقعی از کد)

```
مرورگر (Next.js RTL، درخواست‌های نسبی /api/*)
   │  (هیج localhost در کد مرورگر نیست؛ خریدهای auth در cookie HttpOnly)
   ▼
Next server (next.config.ts › rewrites) ──► /api/:path* ──► BACKEND_ORIGIN (پیش‌فرض http://127.0.0.1:8000)
   │
   ▼
FastAPI (app/main.py)
   ├─ middleware: add_security_headers (nosniff, DENY framing, Referrer-Policy, COOP, Permissions-Policy)
   ├─ middleware: csrf_protection (double-submit؛ Origin/Referer same-origin؛ strict = X-CSRF-Token؛ حالت "off" برای ابزارها)
   ├─ lifespan: enforce_production_settings (APP_ENV=production با secrets ضعیف → RuntimeError)
   │             + seed_database() + load_runtime_overrides_from_db()
   └─ routers (/api/v1/...)
        ├─ auth        (OTP legacy، register، login با رمز، recovery، CSRF، logout)
        ├─ account / plans / curriculum / feedback / capabilities
        ├─ tutor / exams / flashcards / phase4_admin / phase5 / phase6 / admin*  …
        ▼
   Dependencies (app/api/dependencies.py / rbac_deps.py)
   require_student · require_admin (legacy shared-password session **یا** user session با نقش admin/super_admin)
   require_roles / require_moderator_role / require_flashcards_enabled (feature flag)
        ▼
   Services
   ├─ retrieval_service (Qdrant + lexical/PostgreSQL fallback؛ فیلتر truth:
   │    Book.status==ready  AND  Book.catalog_status ∈ allowed_student_catalog_statuses()
   │    AND BookPage.status==done)
   ├─ multi_grade_rag (کنکور 10–12 یک رشته؛ همان فیلترها)
   ├─ capability_runtime ──► ai_gateway ──► core/llm_client.py (تنها جایی که SDK وارد می‌شود)
   │    quota (per-capability) + audit (ai_audit_logs) + grounding_guard (flag-only)
   ├─ ingestion: admin upload → BackgroundTasks → kb_ingestion_service
   │    (job rows در جدول kb_ingestion_jobs؛ status: queued→processing→completed/failed/cancelled)
   │    ⇒ پس از پایان پردازش: book.status = ready (خودکار)؛ figure extraction؛ سپس docs مسیر needs_review برای صفحات نامطمئن
   ├─ sm2 (الگوریتم؛ مستقل از UI) · flashcard_service · exam_service (konkoor/final، نمره سمت سرور)
   └─ rate_limiter (Redis sliding-window + fallback in-process) · chat_stream (Redis، با fallback) · payment_provider (demo) · sms_provider (demo/kavenegar/sms.ir/webhook)
        ▼
   PostgreSQL (پیش‌فرض تولید؛ SQLite فقط demo/tests) · Qdrant (vector؛ اختیاری) · Redis (اختیاری)
```

**مسیر احراز هویت مرورگر:** ورود OTP/رمز → پاسخ شامل `token` (در کلاینت در `sessionStorage[iran_tutor_user_token]`) + cookie HttpOnly `iran_tutor_user`؛ CSRF double-submit با cookie خواندنی `iran_tutor_csrf` (هدر `X-CSRF-Token`)؛ `AppProvider` در ۴۰۱ به `darsyar:session-expired` می‌فرستد؛ `authFetch` در `lib/apiClient.ts` با in-flight de-duplication و CSRF خودکار.

**ادمین:** دو مسیر مستقل می‌توانند وارد شوند — (۱) session legacy با رمز مشترک (`ADMIN_USERNAME`/`ADMIN_PASSWORD`): cookie HttpOnly `iran_tutor_admin` + `X-Admin-Token`/Bearer/(X-Admin-Username+X-Admin-Password)؛ (۲) user session با نقش `admin`/`super_admin`. بدون یکی از این‌ها: 401؛ لاگین‌شدهٔ غیر‌ادمین: 403 (جزئیات در ماتریس).

---

## ۵. موجودی صفحات و routeها

### ۵.۱ صفحات فرانت‌اند (App Router؛ 22 route ساخته‌شده؛ build ✅)

| گروه | مسیر | فایل |
|---|---|---|
| دانش‌آموز | `/` (StudentApp: انتخاب پایه/رشته/کتاب، RAG چت، آزمون، flashcard توکار) | `components/StudentApp.tsx` (2579 خط) |
| | `/flashcards` | `app/flashcards/page.tsx` + `FlashcardsWorkspace.tsx` + `FlashcardStudy.tsx` |
| | `/deep-solve` `/mistakes` `/mastery` `/notebook` `/living-book` | `app/<feature>/page.tsx` + `*Workspace.tsx` |
| | `/study/[bookId]` (dynamic؛ ImmersiveReader) | `app/study/[bookId]/page.tsx` |
| حساب | `/account/profile`، `/account/help`، `/account/upgrade`، `/account/settings{,/general,/appearance,/notifications,/privacy,/storage}` | `app/account/**` |
| ادمین | `/admin` (پنل اصلی، 3593 خط)، `/admin/providers`، `/admin/observability`، `/admin/roles`، `/admin/users/[id]` (dynamic) | `app/admin/**` + `Admin*Panel.tsx` |
| | `/admin` از `AdminGate` (sessionStorage token + cookie) برای زیرصفحه‌ها استفاده می‌کند | `components/AdminGate.tsx` |

**مسیر `/podcast` وجود ندارد** (Route، API، worker، هیچ اشاره‌ای در کد نیست). تنها قابلیت صوتی موجود، TTS متن منتخب است (`POST /api/v1/tts`, capability `audio_tts`).

### ۵.۲ فهرست کامل routeهای API (239 عملیات = path × method؛ استخراج‌شده از `app.openapi()`، فرمان در پیوست B)

| حوزه | تعداد | نمونه‌ها |
|---|---:|---|
| `/api/v1/admin/*` | 113 | auth (login/logout/session)، users (CRUD/role/activation/sessions/credits/password/audit)، books (upload-and-ingest/reprocess/approval/pages/…)، kb (ingest/jobs/figures)، providers، routes، quotas (+ per-feature)، skills (CRUD/rollback/test)، capabilities، audit-logs، overview، search، mastery، flashcards، phase6، curriculum catalog import، action-logs |
| `/api/v1/auth/*` | 14 | OTP legacy، register (3 مرحله)، login، change/recover، csrf، me (GET/PUT)، logout |
| `/api/v1/account/*` | 20 | profile/avatar/phone-otp، preferences، storage/files (لیست/آپلود/حذف/دانلود/quota)، sessions، search |
| `/api/v1/curriculum/*` | 11 | grades/majors/branches/fields/cycles/academic-years/subjects، books، tree، search، figures image |
| `/api/v1/tutor/*` | 15 | ask، ask-image، ask-audio، sessions (CRUD/search/trash/restore/permanent)، stream + stream/{id} (+stop) |
| `/api/v1/flashcards/*` | 23 | decks/cards (CRUD)، generate، review، sessions (create/active/get/patch/shuffle/restart/complete)، due، library/copy، export anki/csv، explain |
| `/api/v1/exams/*` | 4 | create/get/submit/list |
| `/api/v1/plans/*` | 5 | plans، checkout، usage، verify (GET/POST) |
| `/api/v1/notebooks/*` | 12 | notebooks (CRUD) + blocks (CRUD) + inline propose/accept/reject + export.md |
| `/api/v1/immersive/*` | 4 | کتاب، assist، pages/{n} + image |
| `/api/v1/mastery/*` | 3 | books/{id} (+objectives)، evidence |
| `/api/v1/mistakes/*` | 4 | list، practice-set، answer، flashcard |
| `/api/v1/deep-solve/*` | 4 | sessions (+actions) |
| `/api/v1/living-book/*` | 1 | chapters/{chapter_number} |
| `/api/v1/capabilities`, `/plans`, `/tts`, `/visualize`, `/system/status`, `/health`, `/feedback/flag` | 7 | me / checkout / روخوانی / نمودار / وضعیت / health / flag |

فهرست خط‌به‌خط در **پیوست A** (239 سطر) آمده است.

---

## ۶. موجودی مدل‌ها و مایگریشن‌ها

### ۶.۱ مدل‌ها (app/models — 49 کلاس؛ جداول واقعی)

- `auth.py`: User، UserSession، OtpCode
- `curriculum.py`: Grade، Major، Subject، EducationCycle/Branch، FieldOfStudy، AcademicYear، Book، BookPage، BookCurriculumLink، LearningObjective، CurriculumUnit، ObjectivePrerequisite، BookPageObjective، SourceFigure (+ enums BookStatus/PageStatus)
- `chat.py`: ChatSession
- `exam.py`: ExamSession (+ ExamStatus)
- `flashcards.py`: FlashcardDeck، Flashcard (cards)، FlashcardReview، FlashcardStudySession
- `capabilities.py`: Capability، Skill، SkillVersion
- `governance.py`: AiProvider، FeatureModelRoute، UserQuota، AiAuditLog (+ BillingSettings? خیر)
- `concepts.py`: ConceptLink
- `learner_memory.py`: LearnerMemory، LearningEvidence
- `phase5.py`: MistakeBankItem، DeepSolveSession، MasteryBookSettings، MasteryChapterProgress، QuizValidationLog، AdminActionLog
- `phase6.py`: Notebook، NotebookBlock، LivingBookCache، AudioCacheEntry
- `billing/plans/payments` (در `auth.py`/`phase6.py`/`governance.py`): Plan، BillingSettings، PaymentTransaction، TokenUsageLog
- `UserFile` (account storage)

### ۶.۲ Alembic

- **23 revision**؛ single head **`c9d0e1f2a3b4`**؛ mergeهای چندشاخه در d1e2f3a4b5c6 (پدران d4e5f6a7b8c9 و f6a7b8c9d0e1).
- مایگریشن‌ها قابل‌بازگشت‌اند (نمونه: `c9d0e1f2a3b4` روی PostgreSQL با downgrade/re-upgrade تأیید شد؛ `d4e5f6a7b8c9` طبق RELEASE_READINESS قبلاً تأیید شده بود).
- قاعدة پروژه: production schema فقط با Alembic؛ `create_all` فقط برای demo/tests (در مسیر production ممنوع).

### ۶.۳ رجیستری قابلیت‌ها و Skills (seed)

- **14 capability** (همه `is_enabled: true` به‌صورت پیش‌فرض؛ ادمین می‌تواند خاموش کند): chat, solve, quiz, multimodal, flashcards, immersive_reader, deep_solve, quiz_validator, mistake_bank, mastery_path, learning_notebook, web_visualize, living_book, audio_tts.
- **12 skill** (tutor_core, solve_core, quiz_generator, vision_ocr, flashcard_generator, immersive_reader_core, deep_solve_core, quiz_validator, learning_notebook_inline, web_visualize_core, living_book_core, audio_tts_core) — seed فقط slugهای موجود را اضافه می‌کند و هرگز edit ادمین را overwrite نمی‌کند.

---

## ۷. زیرساخت و عملیات

- `docker-compose.yml`: postgres:16 (loopback 5432)، qdrant (6333/6334)، redis:7 (6379)؛ Compose فقط infrastructure است.
- Production: `APP_ENV=production` + guard در production_guard (secrets ضعیف/پیش‌فرض → توقف startup).
- Rate limit: Redis sliding-window؛ نبود Redis/قطع ارتباط → شمارندهٔ in-process (log warning `rate_limiter.redis_unavailable`). **پری‌منشن تک‌worker** (طبق RELEASE_READINESS §4 step 4).
- Chat stream: Redis-backed registry؛ fallback in-memory؛ `POST/GET /api/v1/tutor/stream*`.
- Storage: `backend/storage/` (git-ignored) برای PDF/تصاویر/کش TTS؛ demo assets توسط seed ساخته می‌شوند.
- **Worker جداگانه‌ای برای هیچ‌چیز وجود ندارد** (نه پادکست، نه ingestion): همهٔ کارهای پس‌زمینه با `BackgroundTasks` داخل همان پروسهٔ FastAPI اجرا می‌شوند؛ وضعیت jobs در جدول `kb_ingestion_jobs` قابل‌رهگیری/cancel است (`POST /api/v1/admin/kb/jobs/{id}/cancel`). ریسک: ری‌استارت پروسه، کار ناتمام را متوقف می‌کند؛ recovery job exists نیست (jobها تا ابد `processing` می‌مانند) — مستندسازی به‌عنوان ریسک.

---

## ۸. فایل‌های حجیم و مرزهای استخراج تدریجی پیشنهادی

(استخراج **پیشنهادی** است؛ در این فاز هیچ تبدیلی انجام نشده. قاعده: استخراج پشت تست‌های موجود، در PRهای کوچک.)

| فایل (خطوط) | مرزهای پیشنهادی استخراج |
|---:|---|
| `backend/app/api/admin.py` (3654) | جدا به `admin_books.py` (آپلود/پردازش/صفحات/approval/status)، `admin_providers.py` (providers/routes/quotas/test-ai/test-sms/test-vector)، `admin_settings.py` (settings/billing/preferences/overview/search)، `admin_audit.py`، `admin_curriculum.py`؛ الگوی موجود: `admin_users.py` از قبل جدا شده است |
| `frontend/app/admin/page.tsx` (3593) | هر tab بزرگ به کامپوننت مستقل (Panels از قبل وجود دارند: AdminKbPanel, AdminPhase1Panels…)؛ فایل فقط shell + state باشد |
| `frontend/components/StudentApp.tsx` (2579) | استخراج: `StudentSidebar`، `ChatComposer`، `ExamLauncher`، `FlashcardNudge` |
| `frontend/components/AdminUsersPanel.tsx` (1322) / `AdminIntegrationsPanel.tsx` (1260) | جدول لیست + فرم ویرایش + modals را جدا کن |
| `backend/app/services/retrieval_service.py` (1188) | `qdrant_path`، `lexical_path`، `postgres_fulltext_path`، `citation_builder`؛ قراردادهای خروجی را ثابت نگه دار |
| `backend/app/services/flashcard_service.py` (1152) | `flashcard_generator`، `flashcard_explain`، `flashcard_library` |
| `backend/app/services/admin_user_service.py` (1087) | `rank_policy` (last-super_admin)، `sessions`، `credits` |
| `backend/app/services/auth_service.py` (741) | `otp_flow`، `password_flow`، `recovery` |
| `frontend/components/FlashcardsWorkspace.tsx` (914) / `FlashcardStudy.tsx` (669) | قابل قبول؛ فقط در صورت رشد بیشتر بشکن |
| `frontend/lib/preferences.ts` (595) | جدا به `preferences-core` / `preferences-schema` |
| `frontend/components/GlobalSearch.tsx` (792) | query building را جدا کن |

---

## ۹. تناقض‌های مستندات با کد (و پیشنهاد اصلاح در فازهای بعد)

| # | سند (خط/بخش) | ادعا | واقعیت در کد | شدت | اقدام پیشنهادی |
|---|---|---|---|---|---|
| 1 | `README.md` — بخش «هشدار امنیتی» و پیش‌گفتار: «APIهای ادمین و معلم هنوز احراز هویت ندارند و فقط برای توسعهٔ محلی‌اند» | ادمین بدون auth | `require_admin` روی همهٔ مسیرهای `/api/v1/admin/*` (به‌جز login/logout/session)؛ ۵۰+ مسیر با آن محافظت می‌شوند؛ 401/403 تست‌شده (`test_admin_routes_reject_anonymous_and_students`)؛ tutor/account/exams با `require_student` | **بالا (امنیتی/حقوقی)** | اصلاح README در فاز بعد: auth کامل است؛ رمز پیش‌فرض demo (`admin/123`) فقط محلی و Production در حال `APP_ENV=production` refuses startup |
| 2 | `README.md` — «کنکور واقعاً چندپایه، احراز هویت پیامکی، پلن/سهمیه و مجوزهای ادمین کامل نشده‌اند» | این‌ها ناموجودند | `multi_grade_rag.py` (۱۰–۱۲ همان رشته) موجود و فیلتر کتاب روی آن اعمال است؛ OTP+register+login+recovery موجود؛ plans/quotas/tokens موجود؛ RBAC ۶ نقشی + `require_admin` + last-super_admin protection موجود | **بالا** | README باید به واقعیت به‌روز شود |
| 3 | `docs/RELEASE_READINESS.md` §1/§4 | «head = `d4e5f6a7b8c9`»؛ «308 passed، 1 skipped» | head اکنون `c9d0e1f2a3b4`؛ **446 passed, 1 skipped** | متوسط | به‌روزرسانی اعداد و head در فاز بعد |
| 4 | `docs/PHASE0_INVENTORY.md` | «112 passed» (branch/base قدیمی) | همان تست‌ها اکنون **446 passed** (۳۷ فایل) | متوسط | به‌عنوان سند تاریخی برچسب بخورد یا آرشیو شود |
| 5 | `docs/DARSYAR_AGENT_PACK.md` — PHASE 0 gate | «Run existing tests … produce PHASE0_INVENTORY» | واقعی؛ ولی متن PACK مراحل/تاریخ‌ها را به‌عنوان دستور فعلی نشان می‌دهد | پایین | اعلام «historical playbook» در هدر |
| 6 | **قاعدهٔ محصول (غیرقابل‌مذاکره):** «کتاب به‌محض `Book.status == ready` بدون تأیید دستی در فهرست دانش‌آموز قابل مشاهده باشد؛ `catalog_status` نباید override کند» | و در همین پیام فاز تکرار شده است | `curriculum_access.py` → `is_student_visible_book` و `student_book_catalog_clause()` علاوه بر `ready`، `catalog_status ∈ ("approved",)` (غیردمو) را **الزامی** می‌کنند. `catalog_status` فقط با `PATCH /books/{id}/approval` (بعد از ۱۰۰٪ صفحات done + `official_source_url`) ست می‌شود ⇒ کتاب‌های آمادهٔ پردازش‌شده تا قبل از تأیید دستی برای دانش‌آموز **نامرئی**اند. Demo mode استثنا می‌شود (کتاب demo با `catalog_status="demo"` دیده می‌شود) | **بالا (نقض قاعدهٔ محصول)** | تصمیم مالک + فاز اصلاح: حذف یا خنثی‌سازی gate `catalog_status` در مسیر دانش‌آموز (یا تعریف "published" صریح)؛ تا آن زمان فهرست دانش‌آموز خالی‌تر از انتظار خواهد بود |
| 7 | flashcard generation — `flashcard_sources.py` و `flashcard_service.py (explain)` | «فقط صفحه‌های done وارد retrieval شوند» | متن فلش‌کارت/Explain از صفحات `done` **و `needs_review`** خوانده می‌شود | **بالا (نقض قاعدهٔ RAG)** | فاز بعد: فقط `done`؛ `needs_review` فقط برای admin review؛ اضافه‌کردن تست |
| 8 | `README.md` — «`/admin` ابزار آزمایشی بارگذاری/بازبینی‌اند» | ادمین آزمایشی | ادمین کامل است (observability، providers، users، quotas، skills، KB)؛ محافظت‌شده ولی پیش‌فرض امن نیست مگر `APP_ENV=production` | پایین | متن README به‌روز شود |
| 9 | `docs/HOTFIX_AUTH_ADMIN_AUDIT_20261122.md` | «20 Alembic revisions, head a4b5c6d7e8f9» | اکنون **23 revision**، head **c9d0e1f2a3b4** | پایین | سند تاریخی؛ در صورت ارجاع، به‌روز کن |
| 10 | README — «تصحیح پاسخ تشریحی پیاده‌سازی نشده است» | ناموجود | تأیید می‌شود: exam types فقط `konkoor`/`final`، چهارگزینه‌ای؛ نمره سمت سرور؛ هیچ کد descriptive/essay در `exam_service` نیست | دقیق | باقی بماند؛ نیازمند فاز/تصمیم مستقل |
| 11 | README — حالت demo: «ورود با هر شمارهٔ موبایل و کد نمایشی» | demo-code نمایش داده می‌شود | تأیید می‌شود: در `DEMO_MODE`, `demo_code` در پاسخ `request-otp` برمی‌گردد (`auth.py`) | دقیق | بدون تغییر |
| 12 | `docs/RELEASE_READINESS.md` §3 — «skip یعنی PHASE4_PG_URL ست نشده» | ۱ skipped | تأیید می‌شود؛ همین skip در این فاز هم جاری است | دقیق | بدون تغییر |
| 13 | `UI_POLISH_REPORT.md` | «slice 2 partial» | خودش را ناقص اعلام کرده؛ ادعای کاذب ندارد | دقیق | بدون تغییر |
| 14 | backend/.env.demo.example `ADMIN_PASSWORD=123` | رمز ضعیف نمایشی | هشدار لاگ `ADMIN_PASSWORD is a known-weak default`؛ Production با `APP_ENV=production` refuse می‌کند | قابل‌قبول محلی | بدون تغییر؛ فقط هشدار باقی بماند |

**نکات امنیتی تأییدشده (بدون کشف جدید):** کلیدهای provider برنمی‌گردند (`api_key: None`)، SVG با DOMPurify، Mermaid strict، هیچ `NEXT_PUBLIC_*` secret، `ADMIN_PASSWORD` ضعیف فقط محلی، CSRF double-submit پیش‌فرض on.

---

## ۱۰. blockerها و تصمیم‌های مالک پروژه پیش از فاز ۱

1. **تطبیق قانون انتشار خودکار کتاب با کد** (یافتهٔ ۶): حذف gate `catalog_status` در مسیر دانش‌آموز یا تعریف صریح "published"؟ مالک باید تصمیم بگیرد؛ تغییر رفتار است و در این فاز (مستندسازی) انجام نشد.
2. **flashcards از `needs_review`** (یافتهٔ ۷): اصلاح محدود در فاز آتی لازم است.
3. **`/podcast` اصلاً وجود ندارد** (نه route، نه worker، نه مدل). اگر پادکست بخشی از بازطراحی است، نیازمند تعریف فاز مستقل و تصمیم دربارهٔ TTS موجود است.
4. **`needs_review` در RAG?** خیر — RAG (`retrieval_service`, `multi_grade_rag`, `curriculum`, `exam_service`, `account`, `living_book`) به‌درستی فقط `done` می‌گیرد؛ فقط مسیر فلش‌کارت استثناست.
5. **پوشش تست UI ادمین/دانشجو تقریباً صفر است** (فقط `AdminUsersPanel`, `AuthFlowModal`, `FlashcardWorkspace` و `apiClient` تست دارند)؛ بازطراحی بزرگ UI بدون این‌ها ریسک رگرسیون بالا دارد.
6. **`npm run lint` = 14 مسئلهٔ از‌قبل موجود**؛ بازطراحی باید استاندارد "بدون افزایش تعداد" را حفظ کند.
7. **وابستگی تک‌پروسسه‌ای BackgroundTasks برای ingestion** (بدون worker/heartbeat/recovery): اگر بازطراحی ingestion وب می‌خواهد، این تصمیم معماری است.
8. **Fresh-install**: در این checkout اولیه `.venv` و `node_modules` وجود نداشت؛ اسکریپت‌های setup (`scripts/run-live-demo.sh`) این را پوشش می‌دهند ولی برای CI بهتر است مستند شود.

---

## پیوست A — فهرست کامل routeهای API (239 عملیات؛ استخراج‌شده از `app.openapi()`)

<details><summary>فایل کامل (پیوست خودکار)</summary>

```
GET    /api/v1/account/preferences
PUT    /api/v1/account/preferences
POST   /api/v1/account/preferences/reset
GET    /api/v1/account/profile
PUT    /api/v1/account/profile
DELETE /api/v1/account/profile/avatar
GET    /api/v1/account/profile/avatar
POST   /api/v1/account/profile/avatar
POST   /api/v1/account/profile/phone/request-otp
POST   /api/v1/account/profile/phone/verify
GET    /api/v1/account/search
GET    /api/v1/account/sessions
POST   /api/v1/account/sessions/revoke-others
DELETE /api/v1/account/sessions/{session_id}
GET    /api/v1/account/storage
GET    /api/v1/account/storage/files
POST   /api/v1/account/storage/files
DELETE /api/v1/account/storage/files/{file_id}
GET    /api/v1/account/storage/files/{file_id}
GET    /api/v1/account/storage/files/{file_id}/content
GET    /api/v1/admin/action-logs
GET    /api/v1/admin/audit-logs
GET    /api/v1/admin/audit-logs/summary
GET    /api/v1/admin/audit-logs/{audit_id}
POST   /api/v1/admin/audit-logs/{audit_id}/flag
POST   /api/v1/admin/auth/login
POST   /api/v1/admin/auth/logout
GET    /api/v1/admin/auth/session
GET    /api/v1/admin/billing
PUT    /api/v1/admin/billing/plans/{plan_code}
PUT    /api/v1/admin/billing/settings
GET    /api/v1/admin/books
POST   /api/v1/admin/books/upload-and-ingest
DELETE /api/v1/admin/books/{book_id}
PATCH  /api/v1/admin/books/{book_id}
PATCH  /api/v1/admin/books/{book_id}/approval
GET    /api/v1/admin/books/{book_id}/pages
PUT    /api/v1/admin/books/{book_id}/pages/{idx}
GET    /api/v1/admin/books/{book_id}/pages/{idx}/image
GET    /api/v1/admin/books/{book_id}/preview
POST   /api/v1/admin/books/{book_id}/reindex
POST   /api/v1/admin/books/{book_id}/reprocess
GET    /api/v1/admin/books/{book_id}/status
GET    /api/v1/admin/capabilities
POST   /api/v1/admin/capabilities
DELETE /api/v1/admin/capabilities/{key}
GET    /api/v1/admin/capabilities/{key}
PUT    /api/v1/admin/capabilities/{key}
GET    /api/v1/admin/chat-sessions
GET    /api/v1/admin/concept-links
POST   /api/v1/admin/concept-links
DELETE /api/v1/admin/concept-links/{link_id}
POST   /api/v1/admin/curriculum/catalog/import
GET    /api/v1/admin/flashcards/decks
DELETE /api/v1/admin/flashcards/decks/{deck_id}
GET    /api/v1/admin/flashcards/decks/{deck_id}
PATCH  /api/v1/admin/flashcards/decks/{deck_id}/moderation
GET    /api/v1/admin/flashcards/stats
POST   /api/v1/admin/kb/books/{book_id}/benchmark
GET    /api/v1/admin/kb/books/{book_id}/figures
POST   /api/v1/admin/kb/books/{book_id}/figures/extract
POST   /api/v1/admin/kb/books/{book_id}/ingest
POST   /api/v1/admin/kb/books/{book_id}/reindex-chapter
POST   /api/v1/admin/kb/books/{book_id}/reindex-page
GET    /api/v1/admin/kb/figures/{figure_id}/image
GET    /api/v1/admin/kb/jobs
GET    /api/v1/admin/kb/jobs/{job_id}
POST   /api/v1/admin/kb/jobs/{job_id}/cancel
PUT    /api/v1/admin/mastery/books/{book_id}/chapters/{chapter_number}/override
GET    /api/v1/admin/mastery/books/{book_id}/settings
PUT    /api/v1/admin/mastery/books/{book_id}/settings
GET    /api/v1/admin/mastery/evidence
PATCH  /api/v1/admin/mastery/evidence/{evidence_id}/review
GET    /api/v1/admin/overview
GET    /api/v1/admin/phase6/audio-cache
GET    /api/v1/admin/phase6/living-book
GET    /api/v1/admin/preferences
PUT    /api/v1/admin/preferences
POST   /api/v1/admin/preferences/reset
GET    /api/v1/admin/providers
POST   /api/v1/admin/providers
DELETE /api/v1/admin/providers/{provider_id}
PUT    /api/v1/admin/providers/{provider_id}
POST   /api/v1/admin/providers/{provider_id}/test
GET    /api/v1/admin/quotas
PUT    /api/v1/admin/quotas
DELETE /api/v1/admin/quotas/features/{feature_key}
PUT    /api/v1/admin/quotas/features/{feature_key}
GET    /api/v1/admin/routes
PUT    /api/v1/admin/routes
DELETE /api/v1/admin/routes/{feature_key}
GET    /api/v1/admin/search
GET    /api/v1/admin/settings
PUT    /api/v1/admin/settings
POST   /api/v1/admin/settings/reset
POST   /api/v1/admin/settings/test-ai
POST   /api/v1/admin/settings/test-sms
POST   /api/v1/admin/settings/test-vector
GET    /api/v1/admin/skills
POST   /api/v1/admin/skills
DELETE /api/v1/admin/skills/{slug}
GET    /api/v1/admin/skills/{slug}
PUT    /api/v1/admin/skills/{slug}
POST   /api/v1/admin/skills/{slug}/rollback
POST   /api/v1/admin/skills/{slug}/test
GET    /api/v1/admin/users
POST   /api/v1/admin/users
GET    /api/v1/admin/users/audit
POST   /api/v1/admin/users/preview-normalize
GET    /api/v1/admin/users/roles
DELETE /api/v1/admin/users/{user_id}
GET    /api/v1/admin/users/{user_id}
PATCH  /api/v1/admin/users/{user_id}
PUT    /api/v1/admin/users/{user_id}
PUT    /api/v1/admin/users/{user_id}/activation
GET    /api/v1/admin/users/{user_id}/audit
GET    /api/v1/admin/users/{user_id}/credits
PUT    /api/v1/admin/users/{user_id}/credits
GET    /api/v1/admin/users/{user_id}/deep-solve-sessions
GET    /api/v1/admin/users/{user_id}/mastery
DELETE /api/v1/admin/users/{user_id}/memory
GET    /api/v1/admin/users/{user_id}/memory
PUT    /api/v1/admin/users/{user_id}/memory
GET    /api/v1/admin/users/{user_id}/mistakes
POST   /api/v1/admin/users/{user_id}/password
GET    /api/v1/admin/users/{user_id}/quiz-validation
GET    /api/v1/admin/users/{user_id}/quota
POST   /api/v1/admin/users/{user_id}/revoke-sessions
PUT    /api/v1/admin/users/{user_id}/role
GET    /api/v1/admin/users/{user_id}/sessions
POST   /api/v1/admin/users/{user_id}/sessions/revoke-all
DELETE /api/v1/admin/users/{user_id}/sessions/{session_id}
GET    /api/v1/admin/users/{user_id}/usage
GET    /api/v1/auth/csrf
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
PUT    /api/v1/auth/me
POST   /api/v1/auth/password/change
POST   /api/v1/auth/password/recover/complete
POST   /api/v1/auth/password/recover/request-otp
POST   /api/v1/auth/password/recover/verify-otp
POST   /api/v1/auth/register/complete
POST   /api/v1/auth/register/request-otp
POST   /api/v1/auth/register/verify-otp
POST   /api/v1/auth/request-otp
POST   /api/v1/auth/verify-otp
GET    /api/v1/capabilities/me
GET    /api/v1/curriculum/academic-years
GET    /api/v1/curriculum/books
GET    /api/v1/curriculum/books/{book_id}/figures/{figure_id}/image
GET    /api/v1/curriculum/branches
GET    /api/v1/curriculum/cycles
GET    /api/v1/curriculum/fields
GET    /api/v1/curriculum/grades
GET    /api/v1/curriculum/majors
GET    /api/v1/curriculum/search
GET    /api/v1/curriculum/subjects
GET    /api/v1/curriculum/tree
GET    /api/v1/deep-solve/sessions
POST   /api/v1/deep-solve/sessions
GET    /api/v1/deep-solve/sessions/{session_id}
POST   /api/v1/deep-solve/sessions/{session_id}/actions
GET    /api/v1/exams
POST   /api/v1/exams
GET    /api/v1/exams/{exam_id}
POST   /api/v1/exams/{exam_id}/submit
POST   /api/v1/feedback/flag
DELETE /api/v1/flashcards/cards/{card_id}
PATCH  /api/v1/flashcards/cards/{card_id}
POST   /api/v1/flashcards/cards/{card_id}/explain
GET    /api/v1/flashcards/decks
POST   /api/v1/flashcards/decks
DELETE /api/v1/flashcards/decks/{deck_id}
GET    /api/v1/flashcards/decks/{deck_id}
PATCH  /api/v1/flashcards/decks/{deck_id}
POST   /api/v1/flashcards/decks/{deck_id}/cards
GET    /api/v1/flashcards/decks/{deck_id}/export/anki
GET    /api/v1/flashcards/decks/{deck_id}/export/csv
GET    /api/v1/flashcards/due
POST   /api/v1/flashcards/generate
GET    /api/v1/flashcards/library
POST   /api/v1/flashcards/library/{deck_id}/copy
POST   /api/v1/flashcards/sessions
GET    /api/v1/flashcards/sessions/active
GET    /api/v1/flashcards/sessions/{session_id}
PATCH  /api/v1/flashcards/sessions/{session_id}
POST   /api/v1/flashcards/sessions/{session_id}/complete
POST   /api/v1/flashcards/sessions/{session_id}/restart
POST   /api/v1/flashcards/sessions/{session_id}/shuffle
POST   /api/v1/flashcards/{card_id}/review
GET    /api/v1/immersive/books/{book_id}
POST   /api/v1/immersive/books/{book_id}/assist
GET    /api/v1/immersive/books/{book_id}/pages/{pdf_page_index}
GET    /api/v1/immersive/books/{book_id}/pages/{pdf_page_index}/image
GET    /api/v1/living-book/{book_id}/chapters/{chapter_number}
GET    /api/v1/mastery/books/{book_id}
GET    /api/v1/mastery/books/{book_id}/objectives
POST   /api/v1/mastery/evidence
GET    /api/v1/mistakes
GET    /api/v1/mistakes/practice-set
POST   /api/v1/mistakes/{item_id}/answer
POST   /api/v1/mistakes/{item_id}/flashcard
GET    /api/v1/notebooks
POST   /api/v1/notebooks
DELETE /api/v1/notebooks/{notebook_id}
GET    /api/v1/notebooks/{notebook_id}
PATCH  /api/v1/notebooks/{notebook_id}
POST   /api/v1/notebooks/{notebook_id}/blocks
DELETE /api/v1/notebooks/{notebook_id}/blocks/{block_id}
PATCH  /api/v1/notebooks/{notebook_id}/blocks/{block_id}
POST   /api/v1/notebooks/{notebook_id}/blocks/{block_id}/inline/accept
POST   /api/v1/notebooks/{notebook_id}/blocks/{block_id}/inline/propose
POST   /api/v1/notebooks/{notebook_id}/blocks/{block_id}/inline/reject
GET    /api/v1/notebooks/{notebook_id}/export.md
GET    /api/v1/plans
POST   /api/v1/plans/checkout
GET    /api/v1/plans/usage
GET    /api/v1/plans/verify
POST   /api/v1/plans/verify
GET    /api/v1/system/status
POST   /api/v1/tts
POST   /api/v1/tutor/ask
POST   /api/v1/tutor/ask-audio
POST   /api/v1/tutor/ask-image
GET    /api/v1/tutor/sessions
POST   /api/v1/tutor/sessions
GET    /api/v1/tutor/sessions/search
GET    /api/v1/tutor/sessions/trash
DELETE /api/v1/tutor/sessions/{session_id}
GET    /api/v1/tutor/sessions/{session_id}
PUT    /api/v1/tutor/sessions/{session_id}
DELETE /api/v1/tutor/sessions/{session_id}/permanent
POST   /api/v1/tutor/sessions/{session_id}/restore
POST   /api/v1/tutor/stream
GET    /api/v1/tutor/stream/{stream_id}
POST   /api/v1/tutor/stream/{stream_id}/stop
POST   /api/v1/visualize
GET    /health
```

(TOTAL 239)

</details>

## پیوست B — فرمان‌های استخراج‌شده برای این گزارش

```bash
# baseline
cd backend && ./.venv/bin/python -m pytest -q tests      # 446 passed, 1 skipped, 128.15s
cd frontend && npm test && npm run lint && npm run build  # 41 passed; 14 problems; exit 0
cd backend && ./.venv/bin/alembic heads                  # c9d0e1f2a3b4 (head)
# فهرست routeها (239):
python -c "from app.main import app; spec=app.openapi(); [print(m.upper(), p) for p,ops in sorted(spec['paths'].items()) for m in ops if m.lower() in ('get','post','put','patch','delete')]"
```

<!-- APPENDIX_END -->
