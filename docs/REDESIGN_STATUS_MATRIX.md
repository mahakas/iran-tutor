# ماتریس وضعیت قابلیت‌ها — فاز ۰۰ بازطراحی Darsyar

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **شاخه:** `arena/b0c11271-iran-tutor` @ `da1dce7`
> **مبنا:** فقط کد و تست‌های این checkout؛ هیچ ادعای بدون شواهد ثبت نشده است.

**راهنمای ستون‌ها**

| ستون | معنی |
|---|---|
| `موجود در کد` | پیاده‌سازی در BE/FE هست؟ |
| `API موجود` | endpoint(های) لازم وجود دارند؟ (مسیرها از کد استخراج شده‌اند) |
| `UI موجود` | صفحه/کامپوننت کار می‌کند و همه کنترل‌ها به دادهٔ واقعی وصل‌اند؟ |
| `تست موجود` | تست خودکار (BE pytest / FE jsdom) وجود دارد؟ |
| `وضعیت اعتبارسنجی` | `تأییدشده` = این فاز مستقیم با کد/اجرای تست سنجیده شد؛ `تأیید جزئی` = کد سالم است ولی آزمون کامل/مرورگر ندارد؛ `ناسازگار` = با قاعدهٔ محصول مغایرت دارد؛ `ناقص` = بخشی پیاده نشده |
| `اقدام پیشنهادی` | برای بازطراحی |

**راهنمای اعتبارسنجی سطح تست:** «BE» = این فاز با `pytest` سبز شد (446 passed، 1 skipped)؛ «FE» = `npm test` (41)؛ «code» = خواندن کد، بدون اجرا؛ «none» = بدون آزمون خودکار.

---

## احراز هویت و نشست

| قابلیت | کد | API | UI | تست | اعتبارسنجی | اقدام پیشنهادی |
|---|:-:|:-:|:-:|:-:|---|---|
| ورود OTP (legacy `request-otp`/`verify-otp`) | ✅ | ✅ `POST /api/v1/auth/request-otp`, `/verify-otp` | ✅ AuthFlowModal | ✅ BE+FE (`test_user_auth_admin`, `AuthFlowModal.test.tsx`) | تأییدشده | حفظ؛ نامزد deprecation تدریجی به‌نفع register/login |
| ثبت‌نام (OTP → password) `register/request-otp`, `verify-otp`, `complete` | ✅ | ✅ | ✅ AuthFlowModal | ✅ BE | تأییدشده | حفظ |
| ورود با تلفن+رمز `POST /auth/login` | ✅ | ✅ | ✅ | ✅ BE | تأییدشده | حفظ |
| بازیابی رمز `password/recover/{request-otp,verify-otp,complete}` | ✅ | ✅ | ✅ | ✅ BE (`test_password_recovery_revokes_every_session`) | تأییدشده | حفظ (revoke سراسری نشست‌ها اعمال می‌شود) |
| تغییر رمز `password/change` | ✅ | ✅ | ✅ (account/profile) | ✅ BE | تأییدشده | حفظ |
| نشست سرورمحور (HMAC token + `user_sessions` row؛ revoke فوری) | ✅ | ✅ (logout، me، sessions) | ✅ | ✅ BE | تأییدشده | حفظ؛ تنها منبع حقیقت اعتبار توکن همین ردیف‌هاست |
| کوکی نشست HttpOnly `iran_tutor_user` (+ `X-User-Token`/Bearer fallback) | ✅ | ✅ | ✅ | ✅ code | تأییدشده | حفظ |
| CSRF double-submit (`iran_tutor_csrf` + `X-CSRF-Token`) | ✅ | ✅ `GET /auth/csrf` | ✅ `apiClient.ts` خودکار | ✅ BE (`test_bugfix_hardening`) | تأییدشده | `CSRF_ENFORCEMENT=on` پیش‌فرض؛ `strict` اختیاری؛ `off` فقط برای ابزارها |
| ذخیرهٔ توکن سمت کلاینت در `sessionStorage[iran_tutor_user_token]` | ✅ | — | ✅ AppProvider | ✅ code | تأییدشده (طراحی آگاهانه: iframe preview) | مستند نگه دارید؛ cookie HttpOnly منبع اصلی auth است |
| نقش‌ها و RBAC (student 10 / guardian 20 / teacher 30 / moderator 40 / admin 50 / super_admin 60) | ✅ | ✅ `require_roles`, `/api/v1/admin/*` | ✅ | ✅ BE | تأییدشده | حفظ؛ در بازطراحی فرانت، permissionها همچنان server-side enforce می‌شوند |
| ادمین: نشست legacy رمز مشترک (`iran_tutor_admin` cookie / `X-Admin-Token`) | ✅ | ✅ `POST /admin/auth/login`, `/logout`, `/session` | ✅ | ✅ BE | تأییدشده | حفظ تا حذف کامل؛ تکیه بر نقش بهتر است |
| ادمین: user session با نقش admin/super_admin (ورود هم‌ردیف با legacy) | ✅ | ✅ (همان `require_admin`) | ✅ | ✅ BE | تأییدشده | حفظ |
| محافظت last-super_admin (کاهش رتبه/حذف ممنوع) | ✅ | ✅ | ✅ UI غیر فعال | ✅ BE (`admin_user_service`) | تأییدشده | حفظ |
| soft-delete و revoke نشست‌ها روی تغییر نقش/رمز | ✅ | ✅ | ✅ | ✅ BE | تأییدشده | حفظ |

## ادمین (`/admin*`)

| قابلیت | کد | API | UI | تست | اعتبارسنجی | اقدام پیشنهادی |
|---|:-:|:-:|:-:|:-:|---|---|
| `/admin` پنل اصلی (مرور، کتاب‌ها، KB، users، capabilities…) | ✅ | ✅ 50+ مسیر | ✅ `app/admin/page.tsx` (3593 خط؛ بزرگ) | ⚠️ فقط فهرست کاربران (`AdminUsersPanel.test.tsx`) | تأیید جزئی | استخراج تدریجی tabها به Panel ها؛ اضافه‌کردن تست برای بارگذاری داده |
| `/admin/providers` (CRUD + تست اتصال با آudit) | ✅ | ✅ | ✅ AdminProvidersPanel | ⚠️ | تأیید جزئی | تست API (mock gateway) کافی است؛ UI کنونی hook نیست |
| `/admin/observability` (audit log فیلترپذیر + drawer) | ✅ | ✅ audit-logs | ✅ AdminObservabilityPanel | ⚠️ | تأیید جزئی | حفظ؛ پوشش تست BE موجود است |
| `/admin/roles` (نقش‌ها، سهمیه‌ها) | ✅ | ✅ roles/quotas | ✅ AdminRolesQuotasPanel | ⚠️ | تأیید جزئی | حفظ |
| `/admin/users/[id]` (جزئیات کاربر، نقش/رمز/sessions/credits/audit) | ✅ | ✅ | ✅ AdminUserDetailPanel/Body | ✅ AdminUsersPanel.test.tsx (list level) | تأیید جزئی | تست نسخه `[id]` اضافه شود |
| Skills registry (CRUD + نسخه‌ها + rollback + test) | ✅ | ✅ | ✅ AdminSkillsPanel | ✅ BE (`test_phase2_capabilities_kb`) | تأییدشده | حفظ |
| Capabilities registry (flags، plans/roles مجاز) | ✅ | ✅ | ✅ AdminCapabilitiesPanel | ✅ BE | تأییدشده | حفظ؛ seed: 14 قابلیت all-enabled |
| Knowledge base ingestion (وب؛ job rows + background tasks) | ✅ | ✅ kb | ✅ AdminKbPanel | ✅ BE | تأییدشده | حفظ؛ ریسک BackgroundTasks مستند شد |
| Source figures + تصویر دانش‌آموز (ready-only) | ✅ | ✅ | ⚠️ UI هنوز رندر نمی‌کند | ✅ BE | تأییدجزئی | Reader UI بعد از بازطراحی تصاویر را رندر کند |
| Quotas per feature (`system_config.quotas.per_feature`) | ✅ | ✅ | ✅ | ✅ BE | تأییدشده | حفظ |
| Grounding guard (citation چک؛ flag-only در audit) | ✅ | (در runtime) | (audit queue) | ✅ BE | تأییدشده | حفظ؛ ادمین صف `grounding_mismatch` را ببیند |
| Admin user management (rank policy, activate/password/sessions/credits) | ✅ | ✅ | ✅ | ✅ BE | تأییدشده | حفظ |

## کتاب و RAG (منبع دانش)

| قابلیت | کد | API | UI | تست | اعتبارسنجی | اقدام پیشنهادی |
|---|:-:|:-:|:-:|:-:|---|---|
| ingestion کتاب PDF (Vision OCR → pages) | ✅ | ✅ upload-and-ingest / kb | ✅ AdminKbPanel | ✅ BE (test_phase1_d 39 تست) | تأییدشده | حفظ؛ کیفیت مدل واقعی خارج از scope است |
| **انتشار خودکار کتاب (`ready` → قابل مشاهده دانش‌آموز)** | ⚠️ | ✅ `PATCH /books/{id}/approval` (دستی) | ✅ دکمه تأیید | ✅ BE (test_curriculum_api رفتار فعلی) | **ناسازگار با قاعدهٔ غیرقابل‌مذاکرهٔ محصول** | فاز بازطراحی کتاب: حذف/خنثی‌سازی gate `catalog_status` برای فهرست دانش‌آموز؛ تعریف «Published» صریح؛ migration لازم نیست (فقط policy code) |
| فیلتر `BookPage.status == done` در retrieval | ✅ | — | — | ✅ BE | تأییدشده | حفظ |
| فیلتر `BookStatus.ready` در retrieval | ✅ | — | — | ✅ BE | تأییدشده | حفظ |
| فیلتر `catalog_status == approved` در retrieval و فهرست | ✅ | — | — | ✅ BE (رفتار فعلی) | **ناسازگار** (همان یافتهٔ انتشار خودکار) | به‌همراه ردیف قبل اصلاح شود |
| RAG ترکیبی (Qdrant + lexical/PostgreSQL fallback) | ✅ | ✅ ask | — | ✅ BE | تأییدشده | حفظ |
| کنکور چندپایه (۱۰–۱۲ همان رشته) | ✅ | ✅ ask (konkoor) | ✅ انتخاب کنکور | ⚠️ integration-level | تأیید جزئی | تست contract پهنه رشته اضافه شود |
| استناد اجباری به کتاب/صفحهٔ چاپی | ✅ | ✅ (پاسخ) | ✅ | ✅ BE | تأییدشده | حفظ |
| strict mode بدون منبع → بدون حدس | ✅ | ✅ | — | ✅ BE (catalog_scope mismatch → 回答 نمی‌دهد) | تأییدشده | حفظ |
| **flashcard/explain از صفحات `needs_review`** | ⚠️ | ✅ | — | ⚠️ تست رفتار فعلی را ثبت می‌کند | **ناسازگار با قاعدهٔ RAG** | اصلاح فوری در فاز flashcards: فقط `done` |
| curriculum API (grades/majors/books/tree/search/figures) | ✅ | ✅ | ✅ (picker) | ✅ BE | تأییدشده | حفظ |

## قابلیت‌های آموزشی (مسیر دانش‌آموز)

| قابلیت | کد | API | UI | تست | اعتبارسنجی | اقدام پیشنهادی |
|---|:-:|:-:|:-:|:-:|---|---|
| Chat معلم خصوصی (`tutor`) + citations | ✅ | ✅ ask/stream | ✅ StudentApp | ✅ BE+FE (apiClient) | تأییدشده | حفظ |
| Chat streaming (Redis registry + stop) | ✅ | ✅ stream/stop | ✅ | ✅ BE (test_phase4_memory_rag_streaming) | تأییدشده | حفظ |
| پرسش تصویری `ask-image` | ✅ | ✅ | ✅ | ✅ BE (test_multimodal) | تأییدشده | حفظ |
| پرسش صوتی `ask-audio` | ✅ | ✅ | ✅ | ✅ BE | تأییدشده | حفظ |
| آزمون زمان‌دار konkoor/final (تصحیح سمت سرور، بدون افشای کلید) | ✅ | ✅ exams | ✅ ExamRunner | ✅ BE | تأییدشده | حفظ |
| تصحیح تشریحی (descriptive) | ❌ | ❌ | ❌ | ❌ | **ناقص** (README هم همین را می‌گوید) | تصمیم مالک؛ فاز مستقل |
| فلش‌کارت: deck/card CRUD + تولید از کتاب/اشتباه/چت + استناد | ✅ | ✅ | ✅ FlashcardsWorkspace | ✅ BE+FE | تأییدشده | حفظ (PR #34) |
| فلش‌کارت: SM-2 (got=3/missed=1) idempotent با `session_id` | ✅ | ✅ review | ✅ | ✅ BE | تأییدشده | حفظ؛ SM-2 تغییر نکند |
| فلش‌کارت: جلسات پایدار (create/restore/shuffle/restart/complete) + شمارنده فارسی | ✅ | ✅ sessions/* | ✅ FlashcardStudy | ✅ BE+FE | تأییدشده | حفظ (PR #34) |
| فلش‌کارت: Explain با textbook_strict (+ audit؛ fallback بدون استناد جعلی) | ✅ | ✅ explain | ✅ | ✅ BE+FE | تأییدشده | حفظ |
| فلش‌کارت: خروجی Anki (APKG) و CSV (BOM/escape/anti-formula-injection) | ✅ | ✅ export | ✅ | ✅ BE | تأییدشده | حفظ |
| Deep Solve (گام‌به‌گام + نردبان راهنمایی) | ✅ | ✅ deep-solve | ✅ DeepSolveWorkspace | ✅ BE | تأییدشده | حفظ |
| Mastery Path (امتیاز تسلط فصل + timeline) | ✅ | ✅ mastery | ✅ MasteryWorkspace | ✅ BE | تأییدشده | حفظ |
| Mistake Bank (+ تبدیل به فلش‌کارت) | ✅ | ✅ mistakes | ✅ MistakeBankWorkspace | ✅ BE | تأییدشده | حفظ |
| Learning Notebook (Markdown/فرمول + inline AI propose/accept/reject) | ✅ | ✅ notebooks | ✅ NotebookWorkspace | ✅ BE | تأییدشده | حفظ |
| Living Book (کتابچهٔ شب امتحان + quiz_validator) | ✅ | ✅ living-book | ✅ LivingBookWorkspace | ✅ BE | تأییدشده | حفظ |
| Web Visualize (Mermaid strict + SVG allowlist) | ✅ | ✅ visualize | ✅ | ✅ BE | تأییدشده | حفظ |
| Immersive Reader (`/study/[bookId]`؛ صفحه کتاب + assist + تصاویر) | ✅ | ✅ immersive | ✅ ImmersiveReader | ⚠️ FE (فقط کد) | تأیید جزئی | تست FE reader اضافه شود |
| روخوانی صوتی متن منتخب (TTS، cache، quota) | ✅ | ✅ `/api/v1/tts` | ✅ AudioButton (reader) | ✅ BE | تأییدشده | حفظ |
| **پادکست (route / worker / heartbeat / recovery)** | ❌ | ❌ | ❌ | ❌ | **ناقص (اصلاً وجود ندارد)** | اگر در scope بازطراحی است، فاز مستقل تعریف شود؛ با TTS موجود تداخل نکند |
| Account (profile/settings/storage/quota/upgrade/plans/payment demo) | ✅ | ✅ account | ✅ | ✅ BE | تأییدشده | حفظ |
| Global search (ادمین) | ✅ | ✅ admin/search | ✅ GlobalSearch | ⚠️ | تأیید جزئی | حفظ |
| Live preview script | ✅ | — | — | — | تأییدشده (README) | مستند بماند |

## زیرساخت/عملیات

| قابلیت | کد | تست | اعتبارسنجی |
|---|:-:|:-:|---|
| PostgreSQL فقط با Alembic | ✅ | ✅ (این فاز: full-chain PG 16.2 + downgrade/re-upgrade) | تأییدشده |
| SQLite فقط demo/tests | ✅ | ⚠️ `alembic upgrade head` روی SQLite در `f3a4b5c6d7e8` (pre-existing) می‌شکند | تأییدجزئی (SQLite chain نیازمند batch mode migration جداگانه است؛ خارج از scope) |
| Redis (rate limit + chat stream) با fallback | ✅ | ✅ code | تأییدشده |
| Qdrant اختیاری با fallback lexical | ✅ | ✅ BE | تأییدشده |
| Production guard (APP_ENV) | ✅ | ✅ BE (test_phase7_followup 14 تست) | تأییدشده |
| docker-compose (postgres/qdrant/redis) | ✅ | ⚠️ اجرا نشد (Docker در sandbox نیست) | تأیید جزئی |

---

## پرتوهای قرمز (اولویت‌های بازطراحی از نگاه مبنا)

1. **قاعدهٔ انتشار خودکار کتاب اعمال نمی‌شود** (فهرست دانش‌آموز دیرتر از واقعی پر می‌شود) — بحرانی‌ترین مغایرت محصول/کد.
2. **flashcards از `needs_review` تغذیه می‌شوند** — نقض مستقیم gate RAG.
3. **پوشش UI test ادمین/دانشجو پایین** — بازطراحی بزرگ UI بدون آن پرخطر است.
4. **`/podcast` ناموجود** — اگر هدف است، فاز جدید؛ اگر نه، حذف از نقشه راه.
5. **`npm run lint`: 14 مشکل از‌قبل موجود** — بودجهٔ بدهی فنی مشخص شود.
6. **اسناد stale** (README/RELEASE_READINESS/PHASE0_INVENTORY) — اصلاح در فاز بعدی مستندسازی.
7. **Single-process BackgroundTasks برای ingestion** — برای کتاب‌های بزرگ/ری‌استارت، ریسک نیمه‌کاره ماندن jobها.
