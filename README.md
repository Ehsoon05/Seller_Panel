# Phantom Hubs Seller Panel

سامانه مستقل مدیریت همکاران فروش فانتوم هابز.

## قابلیت‌ها

- حساب و موجودی مستقل برای هر همکار
- سرویس‌ها و قیمت اختصاصی برای هر حساب
- ساخت مستقیم از پنل‌های فعال Phantom
- تنظیم حجم، زمان، HWID، محدودیت دستگاه و ویژگی‌های پنل ساب
- کسر موجودی تراکنشی، بازگشت خودکار وجه و جلوگیری از شارژ تکراری
- جست‌وجو با نام، Username و لینک اشتراک
- کش مصرف و تاریخ انقضا؛ ارتباط با پنل فقط هنگام زدن دکمه به‌روزرسانی
- فعال و غیرفعال‌کردن سرویس توسط همکار
- رابط RTL واکنش‌گرا برای دسکتاپ و موبایل

## اجرای توسعه

```bash
cp .env.example .env
python -m venv .venv
.venv/bin/pip install -r requirements.txt

cd frontend
pnpm install
pnpm run build
cd ..

.venv/bin/uvicorn backend.main:app --reload --port 8087
```

## استقرار

مقادیر `.env` را تنظیم کنید و سپس:

```bash
docker compose up -d --build
```

دیتابیس اصلی Phantom فقط به‌صورت read-only داخل کانتینر mount می‌شود. اطلاعات
فروشندگان در volume مستقل `seller-data` ذخیره می‌شود.

## تست

```bash
python -m unittest discover -s tests -v
cd frontend && pnpm run build
```

