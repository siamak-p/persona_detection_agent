# عامل JoowMe — راهنمای نصب و راه‌اندازی

## پیش‌نیازها

| نیازمندی              | نسخه      | توضیحات                                |
|-----------------------|-----------|----------------------------------------|
| **Python**            | ‏3.11+    | برای پشتیبانی از async                  |
| **Docker و Docker Compose** | آخرین | برای سرویس‌های زیرساختی              |
| **Git**               | آخرین    | برای دریافت مخزن                       |
| **کارت گرافیک NVIDIA** (اختیاری) | CUDA 12+ | برای مدل تعبیه محلی (BAAI/bge-m3) |
| **کلید API اوپن‌ای**  | —         | الزامی برای LLM، STT و TTS            |

---

## مرحله ۱: دریافت مخزن

```bash
git clone <repository-url> joowme-agent
cd joowme-agent
```

---

## مرحله ۲: ساخت محیط مجازی

```bash
python3 -m venv venv
source venv/bin/activate   # لینوکس / مک
# یا
venv\Scripts\activate      # ویندوز
```

---

## مرحله ۳: نصب وابستگی‌ها

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **نکته:** فایل `requirements.txt` شامل PyTorch با پشتیبانی CUDA است. اگر کارت گرافیک ندارید، ابتدا نسخه CPU را نصب کنید:
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> pip install -r requirements.txt
> ```

---

## مرحله ۴: راه‌اندازی سرویس‌های زیرساختی

تمام سرویس‌های مورد نیاز (Qdrant، PostgreSQL، Phoenix، Prometheus، Grafana) را با Docker Compose راه‌اندازی کنید:

```bash
docker compose up -d
```

سرویس‌هایی که راه‌اندازی می‌شوند:

| سرویس                  | پورت  | توضیحات                                |
|------------------------|-------|----------------------------------------|
| **Qdrant**             | 6333  | پایگاه برداری برای حافظه معنایی       |
| **PostgreSQL 16**      | 5432  | پایگاه رابطه‌ای                       |
| **PostgreSQL Exporter**| 9187  | متریک‌های PostgreSQL برای Prometheus   |
| **Phoenix**            | 6006  | تجسم ردیابی AI/LLM                    |
| **Prometheus**         | 9091  | جمع‌آوری متریک‌ها                     |
| **Grafana**            | 3000  | داشبورد (admin/admin) ⚠️ **در حال توسعه** |

بررسی اجرای سرویس‌ها:

```bash
docker compose ps
```

---

## مرحله ۵: تنظیم متغیرهای محیطی

یک فایل `.env` در ریشه پروژه ایجاد کنید:

```bash
cp .env.example .env   # اگر فایل نمونه وجود دارد
# یا به صورت دستی:
touch .env
```

متغیرهای الزامی زیر را اضافه کنید:

```env
# ──────────────────────────────────────────
# تنظیمات الزامی
# ──────────────────────────────────────────

# کلید API اوپن‌ای
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1    # یا آدرس پروکسی شما

# پایگاه داده PostgreSQL (باید با docker-compose.yaml مطابقت داشته باشد)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=joowme
POSTGRES_USER=joowme
POSTGRES_PASSWORD=joowme

# ──────────────────────────────────────────
# تنظیمات اختیاری (با مقادیر پیش‌فرض)
# ──────────────────────────────────────────

# پایگاه برداری
QDRANT_URL=http://localhost:6333

# برنامه
APP_ENV=development
LOG_LEVEL=INFO
TENANT_ID=default

# مدل‌های LLM (مقادیر پیش‌فرض)
COMPOSER_MODEL=gpt-4.1
CREATOR_MODEL=gpt-4.1
GUARDRAIL_MODEL=gpt-4o-mini
SUMMARIZER_MODEL=gpt-4.1
TONE_MODEL=gpt-4o-mini
FACT_EXTRACTOR_MODEL=gpt-4.1
MEM0_LLM_MODEL=openai/gpt-4o

# دمای مدل‌ها
COMPOSER_TEMPERATURE=0.6
CREATOR_TEMPERATURE=0.7
GUARDRAIL_TEMPERATURE=0.1
SUMMARIZER_TEMPERATURE=0.2
TONE_TEMPERATURE=0.3

# حافظه و تعبیه
MEM0_EMBEDDING_MODEL=BAAI/bge-m3
MEM0_EMBEDDING_DIMS=1024
MESSAGE_COUNT_THRESHOLD=20

# صوتی (اختیاری)
VOICE_ENABLED=true
VOICE_TTS_ENABLED=false
VOICE_STT_MODEL=gpt-4o-audio-preview
VOICE_TTS_MODEL=tts-1
VOICE_TTS_VOICE=alloy

# زمان‌بندها
SCHEDULER_ENABLED=true
TONE_SCHEDULER_INTERVAL_SECONDS=3600
FEEDBACK_SCHEDULER_INTERVAL_SECONDS=28800
```

---

## مرحله ۶: مقداردهی اولیه پایگاه داده

اسکریپت مقداردهی اولیه را اجرا کنید تا تمام جداول مورد نیاز ساخته شوند:

```bash
python scripts/init_databases.py
```

در صورت نیاز به اعمال مهاجرت‌ها:

```bash
python scripts/migrations.py
```

---

## مرحله ۷: دانلود مدل تعبیه (اختیاری)

برای دانلود پیشاپیش مدل تعبیه BAAI/bge-m3 برای استفاده آفلاین:

```bash
python scripts/load_embedding_model.py
```

> اگر این مرحله را رد کنید، مدل به صورت خودکار در اولین اجرا دانلود می‌شود (نیاز به اینترنت).

---

## مرحله ۸: اجرای برنامه

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

یا بدون بارگذاری مجدد خودکار (محیط تولیدی):

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

API در آدرس زیر در دسترس خواهد بود: **http://localhost:8000**

### بررسی اجرای صحیح

```bash
curl http://localhost:8000/health
```

پاسخ مورد انتظار:
```json
{
  "status": "healthy",
  "message": "PetaProcTwin API is running"
}
```

---

## مرحله ۹: اجرای داشبورد Streamlit (اختیاری)

در یک ترمینال جداگانه:

```bash
cd streamlit_ui
streamlit run app.py --server.port 8501
```

داشبورد: **http://localhost:8501**

---

## خلاصه پورت‌های سرویس‌ها

| سرویس                  | آدرس                          | کاربرد                         |
|------------------------|-------------------------------|--------------------------------|
| **API عامل JoowMe**   | http://localhost:8000          | API اصلی                       |
| **مستندات API (Swagger)** | http://localhost:8000/docs | مستندات تعاملی API             |
| **رابط Streamlit**     | http://localhost:8501          | داشبورد مدیریت                 |
| **Qdrant**             | http://localhost:6333          | داشبورد پایگاه برداری          |
| **Phoenix**            | http://localhost:6006          | رابط ردیابی AI                 |
| **Grafana**            | http://localhost:3000          | داشبورد متریک‌ها ⚠️ **در حال توسعه** |
| **Prometheus**         | http://localhost:9091          | استعلام متریک‌ها               |

---

## عیب‌یابی

### خطای اتصال به PostgreSQL
```
مطمئن شوید کانتینرهای داکر در حال اجرا هستند:
  docker compose ps

بررسی لاگ‌های PostgreSQL:
  docker compose logs postgres
```

### خطای اتصال به Qdrant
```
بررسی دسترسی به Qdrant:
  curl http://localhost:6333/healthz
```

### خطا در دانلود مدل تعبیه
```
دانلود پیشاپیش مدل:
  python scripts/load_embedding_model.py

یا تنظیم مدل تعبیه دیگر در .env:
  MEM0_EMBEDDING_MODEL=text-embedding-3-small
```

### خطاهای API اوپن‌ای
```
بررسی کلید API:
  curl https://api.openai.com/v1/models \
    -H "Authorization: Bearer $OPENAI_API_KEY"
```

### تداخل پورت‌ها
```
بررسی استفاده‌کننده از پورت:
  lsof -i :8000

متوقف کردن فرآیند یا تغییر پورت:
  uvicorn main:app --port 8001
```
