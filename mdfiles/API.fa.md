# مستند API عامل JoowMe

> **آدرس پایه:** `http://localhost:8000`
> **فریم‌ورک:** FastAPI نسخه 1.0.0 (عنوان: *PetaProcTwin API*)

---

## فهرست مطالب

- [بررسی سلامت](#بررسی-سلامت)
- [چت](#چت)
- [سازنده (Creator)](#سازنده-creator)
- [مشاهده غیرفعال (Passive)](#مشاهده-غیرفعال-passive)
- [بازخورد رابطه](#بازخورد-رابطه)
- [درخواست‌های برنامه‌ریزی آینده](#درخواستهای-برنامهریزی-آینده)
- [نخ‌های مالی](#نخهای-مالی)
- [فایل‌های صوتی](#فایلهای-صوتی)
- [اعلان‌های WebSocket](#اعلانهای-websocket)
- [مدیریت — زمان‌بندها](#مدیریت--زمانبندها)
- [مانیتورینگ](#مانیتورینگ)

---

## بررسی سلامت

### `GET /health`

وضعیت سلامت سرویس و فهرست endpointهای در دسترس را باز می‌گرداند.

---

## چت

### `POST /api/v1/chat`

ارسال پیام از یک کاربر به AI Twin و دریافت پاسخ.

**درخواست (`ChatRequest`):**

| فیلد            | نوع    | الزامی | پیش‌فرض  | توضیحات                                        |
|-----------------|--------|--------|----------|-------------------------------------------------|
| `user_id`       | string | ✅     |          | شناسه کاربر فرستنده                             |
| `to_user_id`    | string | ✅     |          | شناسه کاربر گیرنده (مالک Twin)                  |
| `language`      | string | خیر   | `"fa"`   | زبان پاسخ (ISO 639-1)                          |
| `message`       | string | خیر   | `""`     | متن پیام (خالی اگر ورودی صوتی باشد)            |
| `message_id`    | string | خیر   | `null`   | شناسه پیام سمت کلاینت                          |
| `conversation_id`| string| ✅     |          | شناسه مکالمه                                   |
| `timestamp`     | string | ✅     |          | زمان به فرمت ISO 8601                          |
| `voice_data`    | string | خیر   | `null`   | داده صوتی کدگذاری شده با Base64                 |
| `input_type`    | string | خیر   | `"text"` | `"text"` یا `"voice"`                          |
| `voice_format`  | string | خیر   | `"webm"` | فرمت صوتی (`webm`، `opus`، `mp3`، `wav`)       |

**پاسخ (`ChatResponse`):**

| فیلد              | نوع    | توضیحات                                |
|-------------------|--------|----------------------------------------|
| `user_id`         | string | شناسه کاربر گیرنده                     |
| `agent_message`   | string | پاسخ تولید شده توسط عامل              |
| `agent_message_id`| string | شناسه پیام تولید شده توسط عامل        |
| `conversation_id` | string | شناسه مکالمه                          |
| `agent_timestamp` | string | زمان تولید پاسخ                       |
| `correlation_id`  | string | شناسه ردیابی                          |
| `agent_voice_url` | string | آدرس فایل صوتی TTS (در صورت وجود)     |
| `output_type`     | string | `"text"` یا `"voice"`                 |

---

## سازنده (Creator)

### `POST /api/v1/creator`

ارسال پیام از مالک (سازنده) به Twin خودش برای یادگیری و مکالمه.

**درخواست (`CreatorRequest`):**

| فیلد          | نوع    | الزامی | پیش‌فرض  | توضیحات                             |
|---------------|--------|--------|----------|--------------------------------------|
| `user_id`     | string | ✅     |          | شناسه کاربر سازنده                   |
| `language`    | string | خیر   | `"fa"`   | زبان پاسخ (ISO 639-1)               |
| `message`     | string | خیر   | `""`     | متن پیام                            |
| `message_id`  | string | خیر   | `null`   | شناسه پیام                          |
| `timestamp`   | string | ✅     |          | زمان ISO 8601                       |
| `voice_data`  | string | خیر   | `null`   | داده صوتی Base64                     |
| `input_type`  | string | خیر   | `"text"` | `"text"` یا `"voice"`               |
| `voice_format`| string | خیر   | `"webm"` | فرمت صوتی                           |

**پاسخ (`CreatorResponse`):** مشابه `ChatResponse` بدون `conversation_id`.

---

## مشاهده غیرفعال (Passive)

### `POST /api/v1/passive`

ثبت پیام‌های مشاهده شده غیرفعال (پیام‌هایی که Twin مستقیماً به آنها پاسخ نمی‌دهد اما از آنها یاد می‌گیرد).

**درخواست:** لیستی از `PassiveRecordItem` (شبیه `ChatRequest` با فیلدهای مشابه).

**پاسخ (`PassiveRecordResponse`):** `{ "received": true, "agent_timestamp": "...", "correlation_id": "..." }`

### `GET /api/v1/passive/last-msgId`

دریافت آخرین شناسه پیام همگام‌سازی شده.

**پاسخ:** `{ "lastMsgId": "..." }`

---

## بازخورد رابطه

### `GET /api/v1/feedback/questions/{user_id}`

دریافت سوالات رابطه و درخواست‌های معلق برای یک کاربر.

### `GET /api/v1/feedback/has-unread/{user_id}`

بررسی وجود سوالات، درخواست‌ها یا نخ‌های مالی خوانده نشده.

### `GET /api/v1/feedback/limit-status/{user_id}`

وضعیت محدودیت تعداد سوال در بازه زمانی.

### `POST /api/v1/feedback/answer`

ثبت پاسخ کاربر به سوال رابطه (با مشخص کردن `question_id` و `relationship_class`).

### `POST /api/v1/feedback/skip`

رد کردن یک سوال رابطه.

### `GET /api/v1/feedback/relationship-classes`

دریافت لیست کلاس‌های رابطه معتبر: `spouse`، `family`، `boss`، `subordinate`، `colleague`، `friend`، `stranger`.

---

## درخواست‌های برنامه‌ریزی آینده

### `GET /api/v1/feedback/future-requests/{user_id}`

دریافت درخواست‌های برنامه‌ریزی آینده معلق برای یک سازنده.

### `POST /api/v1/feedback/future-requests/respond`

ثبت پاسخ سازنده به درخواست برنامه‌ریزی آینده.

### `GET /api/v1/feedback/future-requests/count/{user_id}`

تعداد درخواست‌های معلق.

### `GET /api/v1/feedback/my-requests/{sender_id}`

لیست درخواست‌های ارسال‌شده توسط یک کاربر خاص.

---

## نخ‌های مالی

### `GET /api/v1/feedback/financial-threads/{user_id}`

دریافت نخ‌های مکالمه مالی باز برای یک سازنده، شامل آخرین پیام‌ها و وضعیت.

### `POST /api/v1/feedback/financial-threads/respond`

ثبت پاسخ سازنده به یک نخ مالی.

### `DELETE /api/v1/feedback/financial-threads/{thread_id}`

بستن یک نخ مالی.

---

## فایل‌های صوتی

### `GET /voices/{conversation_id}/{filename}`

دانلود فایل صوتی ذخیره شده. فرمت خروجی: `audio/mpeg`.

---

## اعلان‌های WebSocket

### `WS /api/v1/ws/{user_id}`

اتصال WebSocket برای دریافت اعلان‌های بلادرنگ.

**انواع اعلان:**

| نوع                       | توضیحات                                                 |
|---------------------------|----------------------------------------------------------|
| `future_response`         | سازنده به درخواست برنامه‌ریزی پاسخ داد                  |
| `future_request`          | درخواست برنامه‌ریزی جدید برای سازنده شناسایی شد          |
| `financial_topic`         | موضوع مالی جدید برای سازنده شناسایی شد                  |
| `financial_message`       | پیام جدید به نخ مالی اضافه شد                           |
| `financial_response`      | سازنده به نخ مالی پاسخ داد                              |
| `ping`                    | ضربان قلب سرور (هر ۳۰ ثانیه)                            |

### `GET /api/v1/ws/status`

وضعیت اتصالات WebSocket فعال.

---

## مدیریت — زمان‌بندها

> **پیشوند:** `/api/v1/admin/scheduler`

| مسیر                                              | متد   | توضیحات                                      |
|---------------------------------------------------|-------|-----------------------------------------------|
| `/run/tone`                                        | POST  | اجرای دستی زمان‌بند تشخیص لحن                 |
| `/run/tone-retry`                                  | POST  | اجرای دستی بازپردازش لحن                      |
| `/stats/tone-retry`                                | GET   | آمار صف بازپردازش لحن                         |
| `/run/feedback`                                    | POST  | اجرای دستی زمان‌بند تولید سوالات رابطه        |
| `/run/chat-summary`                                | POST  | اجرای دستی خلاصه‌سازی مکالمه خاص              |
| `/run/retry`                                       | POST  | اجرای دستی بازپردازش خلاصه‌سازی               |
| `/stats/summary-retry`                             | GET   | آمار صف بازپردازش خلاصه                       |
| `/status`                                          | GET   | وضعیت کامل زمان‌بندها                         |
| `/run/passive-summarization`                       | POST  | اجرای دستی خلاصه‌سازی غیرفعال                 |
| `/run/passive-summarization-retry`                 | POST  | اجرای بازپردازش خلاصه‌سازی غیرفعال            |
| `/stats/passive-summarization`                     | GET   | آمار بازپردازش خلاصه‌سازی غیرفعال             |
| `/retry-failed/passive-summarization/{failed_id}`  | POST  | بازپردازش یک خلاصه‌سازی غیرفعال ناموفق خاص   |
| `/failed/passive-summarization`                    | GET   | لیست خلاصه‌سازی‌های غیرفعال ناموفق            |

---

## مانیتورینگ

### `GET /metrics`

نقطه دسترسی متریک‌های Prometheus. شامل: تعداد درخواست HTTP، تاخیر، کدهای وضعیت، مصرف توکن LLM، عملکرد endpointها، و متریک‌های SQLite.
