# معلم خصوصی هوش مصنوعی ایران (Iran AI Tutor)

سکوی معلم خصوصی فارسی مبتنی بر کتاب‌های درسی رسمی ایران. هدف محصول، پاسخ‌گویی مستند به کتاب، فصل و شمارهٔ صفحهٔ چاپی است؛ اگر منبع قابل‌اتکا در کتاب‌های بارگذاری‌شده پیدا نشود، سیستم باید از حدس‌زدن خودداری کند.

پروژه مرحله‌ای ساخته می‌شود. وضعیت فعلی مخزن: **فاز ۱ — خط پردازش PDF و بازبینی انسانی**. موتور RAG، چت دانش‌آموز، پنل وب ادمین، آزمون واقعی، ورودی عکس/صوت و احراز هویت هنوز جزو کارهای بعدی‌اند.

> سرویس‌های ادمین فعلی برای توسعهٔ محلی‌اند و هنوز احراز هویت ندارند. آن‌ها را روی اینترنت عمومی منتشر نکنید.

## ساختار اصلی

| مسیر | توضیح |
|---|---|
| `.kilocode/rules/architecture.md` | قواعد معماری، فازها و رفتار معلم |
| `docker-compose.yml` | PostgreSQL، Qdrant و Redis |
| `.env.example` | تنظیمات نمونهٔ Docker؛ فایل واقعی `.env` را نسازید/کامیت نکنید |
| `backend/` | FastAPI، پردازش PDF، مدل‌های داده و آزمون‌ها |
| `backend/storage/` | PDFهای آپلودشده، تصاویر و خروجی پردازش؛ در Git ثبت نمی‌شود |
| `frontend/` | در فاز رابط کاربری اضافه خواهد شد |

## راه‌اندازی در Ubuntu / WSL2

پیش‌نیازها: Docker Desktop با WSL integration، Python 3.11+ و دسترسی به یک API سازگار با OpenAI برای مدل بینایی.

### ۱. زیرساخت

از ریشهٔ مخزن:

```bash
cp .env.example .env
# در صورت نیاز POSTGRES_PASSWORD را در .env عوض کنید.
docker compose up -d
docker compose ps
```

سرویس‌ها باید وضعیت `healthy` داشته باشند. پورت‌های دیتابیس فقط روی loopback منتشر شده‌اند:

| سرویس | پورت |
|---|---:|
| PostgreSQL | 5432 |
| Qdrant HTTP / gRPC | 6333 / 6334 |
| Redis | 6379 |

### ۲. بک‌اند

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

در `backend/.env` مقدارهای `LLM_BASE_URL`، `LLM_API_KEY` و نام مدل‌های `VISION_MODEL_*` را با اطلاعات سرویس خودتان پر کنید. مقدار `DATABASE_URL` نمونه با تنظیمات پیش‌فرض ریشه هماهنگ است؛ اگر رمز PostgreSQL را عوض کردید، همین‌جا هم آن را عوض کنید.

سپس مهاجرت و API را اجرا کنید:

```bash
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

مستندات API محلی: <http://127.0.0.1:8000/docs>

### ۳. آزمون‌ها

آزمون‌های واحد به `.env`، کلید API یا دیتابیس واقعی نیاز ندارند:

```bash
cd backend
source .venv/bin/activate
pytest -q
```

اسکریپت `scripts/test_ingest.py` ابزار مقایسهٔ مدل‌هاست، نه مجموعهٔ تست pytest؛ برای جلوگیری از اجرای تصادفی آن، pytest فقط مسیر `tests/` را جمع‌آوری می‌کند.

## پردازش کتاب — فاز ۱

برای پایه‌های ۱۰ تا ۱۲، کد رشته الزامی است. PDF را در مسیر دلخواه نگه دارید؛ فایل PDF و خروجی‌های پردازش وارد Git نمی‌شوند.

```bash
cd backend
source .venv/bin/activate
python scripts/ingest_book.py \
  --pdf /path/to/physics12.pdf \
  --grade 12 --major math_physics --title "فیزیک ۳" \
  --start 5 --end 9
```

گزینه‌های مهم:

| گزینه | کاربرد |
|---|---|
| `--dry-run` | فقط برنامهٔ کار را نشان می‌دهد؛ هیچ رندر، فراخوانی مدل یا نوشتنی ندارد |
| `--force` | صفحات انتخاب‌شده را دوباره پردازش می‌کند |
| `--only-failed` | فقط صفحات ناموفق را دوباره تلاش می‌کند |
| `--overwrite-human` | اجازهٔ بازنویسی صفحات اصلاح‌شده توسط انسان را می‌دهد |

خروجی‌ها در `backend/storage/books/<book_id>/` قرار می‌گیرند: JSON/Markdown، تصاویر صفحات و پیش‌نمایش. برای صفحه‌های نامطمئن، خروجی نیازمند بازبینی است و نباید بدون بررسی انسانی به‌عنوان استخراج قطعی تلقی شود.

پیش‌نمایش API پس از پردازش:

```text
GET /api/v1/admin/books/{book_id}/preview?status=all&page_from=2&page_to=5
```

اصلاح دستی صفحه:

```text
PUT /api/v1/admin/books/{book_id}/pages/{pdf_page_index}
{"markdown_content":"...", "printed_page_number":3}
```

### مقایسهٔ دو مدل بینایی

این دستور فقط خروجی مقایسه و HTML پیش‌نمایش می‌سازد و در پایگاه‌داده چیزی ثبت نمی‌کند:

```bash
python scripts/test_ingest.py \
  --pdf /path/to/physics12.pdf --start 2 --end 5 --model both
```

خروجی در `backend/storage/books/<book_id>/compare.html` ساخته می‌شود. این کار API مصرف می‌کند و ممکن است هزینه داشته باشد.
