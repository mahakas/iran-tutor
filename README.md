# معلم خصوصی هوش مصنوعی ایران (Iran AI Tutor)

سکوی معلم خصوصی فارسی مبتنی بر هوش مصنوعی که **فقط** بر پایهٔ کتاب‌های درسی رسمی ایران پاسخ می‌دهد و در پایان هر پاسخ، منبع (کتاب، فصل و شمارهٔ صفحهٔ چاپی) را ذکر می‌کند.

پروژه به‌صورت فازبندی‌شده ساخته می‌شود. وضعیت فعلی: **فاز ۱، گام D** (پردازش کامل PDF با استخراج متن، فرمول و شکل، به‌همراه بازبینی انسانی).

## ساختار پوشه‌ها

| مسیر | توضیح |
|---|---|
| `.kilocode/rules/architecture.md` | قوانین پایدار معماری، فازها، رفتار معلم و قواعد کدنویسی |
| `docker-compose.yml` | سرویس‌های زیرساختی: PostgreSQL، Qdrant و Redis |
| `.env.example` | نمونهٔ متغیرهای محیطی ریشه؛ باید در فایل `.env` کپی و مقداردهی شود |
| `.gitignore` | فایل‌هایی که هرگز نباید کامیت شوند (`.env`، فایل‌های PDF، پوشه‌های داده و `storage`) |
| `backend/` | سرویس FastAPI و ابزارهای پردازش کتاب |
| `backend/storage/` | فایل‌های کتاب و خروجی پردازش؛ در گیت ثبت نمی‌شود |
| `frontend/` | وب‌اپلیکیشن دانش‌آموز (Next.js، راست‌به‌چپ) — در فازهای بعدی |

## راه‌اندازی سرویس‌ها

```bash
cp .env.example .env        # سپس مقادیر را ویرایش کنید
docker compose up -d
docker compose ps           # همهٔ سرویس‌ها باید healthy باشند
```

درگاه‌ها فقط روی `127.0.0.1` باز هستند:

| سرویس | درگاه |
|---|---|
| PostgreSQL | 5432 |
| Qdrant (HTTP / gRPC) | 6333 / 6334 |
| Redis | 6379 |

## راه‌اندازی بک‌اند

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # سپس LLM_BASE_URL، LLM_API_KEY و نام مدل‌ها را وارد کنید
```

مهاجرت‌های پایگاه‌داده:

```bash
.venv\Scripts\alembic upgrade head
```

اجرای API:

```bash
.venv\Scripts\uvicorn app.main:app --reload
```

## پردازش کتاب (فاز ۱، گام D)

کتاب با **عنوان + پایه + رشته** در پایگاه‌داده شناسایی می‌شود. برای پایه‌های ۱۰ تا ۱۲ ارائهٔ `--major` الزامی است.

```bash
cd backend
.venv\Scripts\python scripts\ingest_book.py --pdf data\physics12.pdf --grade 12 \
    --major math_physics --title "فیزیک ۳" --start 1 --end 9
```

گزینه‌های مهم:

| گزینه | کاربرد |
|---|---|
| `--dry-run` | فقط برنامهٔ پردازش را نشان می‌دهد؛ هیچ رندر، فراخوانی LLM یا نوشتنی انجام نمی‌شود |
| `--force` | همهٔ صفحات را دوباره پردازش می‌کند |
| `--only-failed` | فقط صفحات ناموفق را دوباره پردازش می‌کند |
| `--overwrite-human` | اجازه می‌دهد صفحاتی که انسان ویرایش کرده بازنویسی شوند (بدون این گزینه، حتی `--force` هم آن‌ها را حفظ می‌کند) |

پس از پردازش:

- خروجی‌ها در `backend/storage/books/<book_id>/` ذخیره می‌شوند: `book.md`، `book.json`، تصاویر صفحات و خروجی هر مدل.
- در `book.json` مقدار `printed_page_offset` (اختلاف رایج بین شمارهٔ PDF و شمارهٔ چاپی) و فهرست `printed_page_deviations` ثبت می‌شود.
- گزارش پایانی، شمارهٔ صفحه‌های `needs_review` و `failed`، هشدارهای هر صفحه و صفحات دارای انحراف در شمارهٔ چاپی را چاپ می‌کند.

### ادامهٔ پردازش و بازبینی

هر صفحه پس از پردازش بلافاصله در پایگاه‌داده ذخیره می‌شود؛ بنابراین با `Ctrl+C` یا خطای شبکه، کار از همان‌جا ادامه پیدا می‌کند (صفحات `done` دوباره پردازش نمی‌شوند).

```bash
# فقط صفحات ناموفق
.venv\Scripts\python scripts\ingest_book.py --pdf data\physics12.pdf --grade 12 \
    --major math_physics --title "فیزیک ۳" --start 1 --end 9 --only-failed
```

پیش‌نمایش مرورگری (HTML راست‌به‌چپ با KaTeX):

```
GET /api/v1/admin/books/{book_id}/preview?status=all|done|failed|needs_review&page_from=2&page_to=5
```

اصلاح دستی صفحه (نتیجه با `edited_by_human=true` ذخیره و از پردازش‌های بعدی محافظت می‌شود):

```
PUT /api/v1/admin/books/{book_id}/pages/{idx}
{"markdown_content": "...", "printed_page_number": 3}
```

### مقایسهٔ دو مدل (فایل‌محور، بدون نوشتن در پایگاه‌داده)

```bash
.venv\Scripts\python scripts\test_ingest.py --pdf data\physics12.pdf --start 2 --end 5 --model both
```

خروجی مقایسه در `backend/storage/books/<id>/compare.html` ساخته می‌شود.
