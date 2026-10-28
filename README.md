# MILAD CRAFT — وب‌سایت رسمی و فضای کاری کارکنان

وب‌سایت فارسی و راست‌چین سرور Minecraft **MILAD CRAFT** با رابط واکنش‌گرا، حساب یکپارچه، پروفایل، پنل کارکنان، پروژه و تسک، اخطارها، پیام‌رسان، اخبار و مرکز آموزش.

- **آدرس سرور:** `miladcraft.seedloaf.gg`
- **نسخه پیشنهادی:** `1.21.11`
- **تلگرام:** [@Milad_craft](https://t.me/Milad_craft)
- **گیم‌مود اصلی:** Role Play
- **مخزن:** [russhabot/Miladcraft-website](https://github.com/russhabot/Miladcraft-website)

## روند حساب‌ها

1. بازیکن از صفحه ساخت حساب، یک حساب معمولی ایجاد می‌کند.
2. بازیکن و کارکنان از **یک صفحه ورود مشترک** وارد می‌شوند؛ لازم نیست برای کارکنان حساب جداگانه ساخته شود.
3. حساب تازه‌ثبت‌نام‌شده به‌صورت پیش‌فرض نقش بازیکن دارد.
4. **Owner و Developer** می‌توانند از پنل کارکنان یک حساب ثبت‌شده را به یکی از نقش‌های کارکنان ارتقا دهند.
5. بعد از ارتقا، همان نام کاربری، رمز عبور و پروفایل قبلی حفظ می‌شود و مسیر پنل کارکنان در ورود بعدی در دسترس قرار می‌گیرد.
6. Owner و Developer مجموعه دسترسی مدیریتی یکسان دارند؛ رنگ و عنوان نقش آن‌ها متفاوت است.

## نقش‌ها

| نقش | رنگ رابط | قابلیت‌های اصلی |
|---|---|---|
| Owner | قرمز روشن | دسترسی مدیریتی کامل |
| Developer | خاکستری تیره | همان دسترسی‌های Owner |
| Manager | آبی | مدیریت پروژه‌ها، تسک‌ها، اخطارها و محتوای سایت |
| Admin | قرمز تیره | مدیریت پروژه‌ها، تسک‌ها، اخطارها و محتوای سایت |
| H-Builder | بنفش | ساخت پروژه، تعریف تسک و اخطار دادن به Builder |
| Moderator | نارنجی | نقش نظارتی؛ دسترسی مدیریتی اضافی به‌صورت پیش‌فرض ندارد |
| Helper | زرد | نقش پشتیبانی؛ دسترسی مدیریتی اضافی به‌صورت پیش‌فرض ندارد |
| Builder | فیروزه‌ای | مشاهده پروژه‌ها، پیوستن به پروژه و به‌روزرسانی تسک‌های خودش |
| Player | خاکستری | حساب بازیکن، پروفایل، اعلان‌ها، دیدگاه‌ها و بازخورد |

قواعد مجوز سمت سرور در `app.py` تعریف شده‌اند؛ پنهان‌کردن دکمه در HTML به‌تنهایی مجوز محسوب نمی‌شود.

## قابلیت‌ها

### وب‌سایت عمومی
- صفحه اصلی با معرفی سرور، تصاویر قابل‌تغییر، گیم‌مودها، آخرین اخبار و راهنماها.
- کپی آدرس سرور با یک کلیک.
- بررسی وضعیت سرور از طریق سرویس خارجی `api.mcsrvstat.us`. اگر سرویس خارجی پاسخ ندهد، سایت «وضعیت نامشخص» نشان می‌دهد؛ این وضعیت به‌تنهایی اثبات خاموش‌بودن سرور نیست.
- صفحات اخبار و مرکز آموزش، جست‌وجو، برچسب، دیدگاه، پاسخ استف و بازخورد.
- مسیرهای `robots.txt` و `sitemap.xml`.

### حساب یکپارچه
- ثبت‌نام و ورود مشترک برای بازیکن و کارکنان.
- پروفایل مشترک با نام نمایشی، تصویر، معرفی کوتاه، نام Minecraft، Telegram و Discord.
- تغییر رمز عبور با بررسی رمز فعلی.
- اعلان‌ها و تاریخچه دیدگاه‌ها.
- تصویر پروفایل PNG، JPEG، WEBP یا GIF تا حداکثر ۱٫۵ مگابایت.

### پنل کارکنان
- داشبورد نقش‌محور و طراحی مناسب دسکتاپ و موبایل.
- ساخت پروژه با تعداد Builder موردنیاز و عضویت چند Builder در هر پروژه.
- ایجاد تسک برای پروژه، تخصیص به Builder عضو پروژه و تغییر وضعیت تسک.
- ثبت اخطار با دلیل و مدرک تصویر یا ویدئو (حداکثر ۸ مگابایت) یا لینک HTTPS.
- H-Builder فقط می‌تواند برای Builder اخطار ثبت کند.
- فعالیت کارکنان و رویدادهای ورود/خروج از Minecraft.
- پیام‌رسان گروهی کارکنان و پیام خصوصی بین کارکنان.
- مدیریت نقش‌های کارکنان توسط Owner و Developer.
- مدیریت خبرها، مقاله‌ها، برچسب‌ها، پاسخ دیدگاه‌ها و تصاویر صفحه اصلی برای نقش‌های مجاز.

### اتصال Minecraft
وب‌سایت یک endpoint امن برای دریافت رویداد ورود/خروج کارکنان دارد. این endpoint به‌تنهایی از سرور Minecraft رویداد دریافت نمی‌کند؛ برای فعال‌شدن حضور آنلاین باید یک پلاگین سمت سرور رویدادها را به وب‌سایت بفرستد.

- مسیر: `POST /api/minecraft-event`
- Header: `X-MiladCraft-Token: <shared-secret>`
- بدنه ورود: `{"username":"StaffMinecraftName","event":"join"}`
- بدنه خروج: `{"username":"StaffMinecraftName","event":"quit"}`
- متغیر لازم: `MINECRAFT_WEBHOOK_TOKEN`
- فقط نام کاربری حسابی که نقش کارکنان دارد ثبت می‌شود؛ بازیکنان عادی نادیده گرفته می‌شوند.

مستندات تکمیلی: [docs/minecraft-staff-presence.md](docs/minecraft-staff-presence.md)

## فناوری‌ها و ساختار

- Python 3.10+
- Flask
- SQLite
- Jinja templates
- Bleach برای پاک‌سازی محتوای HTML
- Gunicorn برای Railway
- GitHub Actions برای بررسی نحوی و تست‌های خودکار

ساختار اصلی:

```text
Miladcraft-website/
├── app.py
├── requirements.txt
├── Procfile
├── README.md
├── .env.example
├── docs/
│   └── minecraft-staff-presence.md
├── tests/
│   └── test_app.py
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── account_portal.html
│   ├── account_login.html
│   ├── account_register.html
│   ├── account_profile.html
│   ├── dashboard.html
│   ├── academy.html
│   ├── post.html
│   ├── editor.html
│   ├── news.html
│   ├── news_detail.html
│   └── error.html
└── static/
    ├── style.css
    └── logo.svg
```

## اجرای محلی

نیازمند Python 3.10 یا جدیدتر است.

```bash
git clone https://github.com/russhabot/Miladcraft-website.git
cd Miladcraft-website
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "replace-with-a-long-random-secret"
$env:COOKIE_SECURE = "false"
$env:BOOTSTRAP_OWNER_USERNAME = "your-owner-username"
$env:BOOTSTRAP_OWNER_PASSWORD = "use-a-unique-password-at-least-10-characters"
python app.py
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="replace-with-a-long-random-secret"
export COOKIE_SECURE="false"
export BOOTSTRAP_OWNER_USERNAME="your-owner-username"
export BOOTSTRAP_OWNER_PASSWORD="use-a-unique-password-at-least-10-characters"
python app.py
```

سایت در `http://127.0.0.1:8080` در دسترس خواهد بود.

## متغیرهای محیطی

| متغیر | کاربرد |
|---|---|
| `SECRET_KEY` | کلید محرمانه نشست Flask؛ در استقرار حتماً تنظیم شود |
| `COOKIE_SECURE` | برای HTTPS مقدار `true` و برای localhost روی HTTP مقدار `false` |
| `DATA_DIR` | پوشه پیش‌فرض داده‌ها، به‌طور پیش‌فرض `data` |
| `DB_PATH` | مسیر دیتابیس SQLite؛ در صورت تنظیم بر `DATA_DIR` اولویت دارد |
| `PORT` | پورت برنامه، پیش‌فرض `8080` |
| `TELEGRAM_URL` | لینک کانال تلگرام |
| `BOOTSTRAP_OWNER_USERNAME` | نام حساب اولیه Owner |
| `BOOTSTRAP_OWNER_PASSWORD` | رمز اولیه Owner؛ حداقل ۱۰ نویسه |
| `MINECRAFT_WEBHOOK_TOKEN` | راز مشترک برای احراز هویت رویدادهای Minecraft |

حساب bootstrap فقط در صورت نبودن نام کاربری ساخته می‌شود. اگر حساب از قبل وجود داشته باشد، برنامه نقش آن را به Owner تغییر می‌دهد، اما رمز عبور فعلی را بازنویسی نمی‌کند. این متغیرها را با دقت تنظیم کنید.

## استقرار Railway

1. ریپازیتوری و سرویس وب را در Railway متصل کنید.
2. متغیرهای `SECRET_KEY`، `BOOTSTRAP_OWNER_USERNAME` و `BOOTSTRAP_OWNER_PASSWORD` را تنظیم کنید.
3. یک Volume پایدار به سرویس متصل کنید و `DB_PATH` را به فایل داخل Volume اشاره دهید؛ برای مثال `/data/miladcraft.db`.
4. برای سایت HTTPS، مقدار `COOKIE_SECURE=true` باشد.
5. `MINECRAFT_WEBHOOK_TOKEN` را فقط در صورت استفاده از فرستنده سمت سرور تنظیم کنید.
6. Deploy و سپس لاگ‌های build و runtime را بررسی کنید.
7. صفحه اصلی، وضعیت سرور، ثبت‌نام، ورود، پروفایل، ارتقای نقش، پروژه‌ها و ماندگاری داده‌ها را آزمایش کنید.

فرمان اجرا در `Procfile`:

```text
web: gunicorn app:app
```

### پایداری و مهاجرت دیتابیس

داده‌های برنامه در SQLite ذخیره می‌شوند. فایل‌سیستم کانتینر Railway ممکن است موقت باشد؛ بدون Volume پایدار، داده‌ها ممکن است پس از Deploy از دست بروند.

- پیش از استقرار نسخه جدید از فایل دیتابیس فعلی نسخه پشتیبان تهیه کنید.
- این نسخه تلاش می‌کند حساب‌های قدیمی `members` و `staff` را به جدول یکپارچه `accounts` منتقل کند و اطلاعات محتوایی قبلی را حفظ کند.
- مهاجرت حساب‌های قدیمی با نشانگر داخلی یک بار اجرا می‌شود تا نقش‌هایی که بعداً تغییر داده می‌شوند در راه‌اندازی بعدی بازنویسی نشوند.
- مسیر `DB_PATH` را بدون انتقال فایل دیتابیس تغییر ندهید.
- دیتابیس، فایل‌های `.env` و نسخه‌های پشتیبان را به Git اضافه نکنید.

## مسیرهای اصلی

| مسیر | کاربرد |
|---|---|
| `/` | صفحه اصلی |
| `/account` | انتخاب ورود یا ساخت حساب |
| `/account/register` | ثبت‌نام بازیکن |
| `/account/login` | ورود مشترک بازیکن و کارکنان |
| `/account/profile` | پروفایل و تنظیمات حساب |
| `/staff` | داشبورد کارکنان |
| `/staff/promote-member` | ارتقای حساب ثبت‌شده توسط Owner/Developer |
| `/projects/create` | ساخت پروژه |
| `/projects/<id>/join` | پیوستن به پروژه |
| `/warnings/create` | ثبت اخطار |
| `/messages/private` | شروع گفت‌وگوی خصوصی کارکنان |
| `/news` | اخبار |
| `/academy` | مرکز آموزش |
| `/api/server-status` | وضعیت سرور در JSON |
| `/api/minecraft-event` | webhook ورود/خروج Minecraft |

## امنیت و نگه‌داری

- در محیط عمومی از `SECRET_KEY` قوی و محرمانه استفاده کنید.
- برای فرم‌های تغییردهنده داده، توکن CSRF بررسی می‌شود.
- رمزها با Werkzeug hash می‌شوند؛ رمز خام در دیتابیس ذخیره نمی‌شود.
- دسترسی‌های مدیریتی سمت سرور بررسی می‌شوند.
- محتوای HTML مقاله و خبر با Bleach پاک‌سازی می‌شود.
- لینک‌های تصویر و مدارک باید HTTPS باشند؛ فایل‌های آپلودی نوع و اندازه مشخص دارند.
- webhook Minecraft بدون توکن معتبر پاسخ 401 می‌دهد و در صورت تنظیم‌نشدن راز مشترک پاسخ 503 می‌دهد.
- پیش از تغییرات دیتابیس، نسخه پشتیبان بگیرید و بازیابی آن را آزمایش کنید.

## آزمایش‌ها

در محیط توسعه:

```bash
python -m compileall -q app.py tests
python -m unittest discover -s tests -v
```

GitHub Actions این بررسی‌ها را روی شاخه بازسازی و Pull Request اجرا می‌کند.

## نکته‌های عیب‌یابی

- **ورود در localhost کار نمی‌کند:** برای HTTP محلی `COOKIE_SECURE=false` بگذارید.
- **داده‌ها بعد از Deploy ناپدید شده‌اند:** مسیر `DB_PATH` و اتصال Volume را بررسی کنید.
- **وضعیت سرور نامشخص است:** endpoint به سرویس بیرونی وابسته است؛ این وضعیت ممکن است از اختلال سرویس یا شبکه باشد.
- **Minecraft آنلاین نشان داده نمی‌شود:** فرستنده سمت سرور باید نصب و با همان `MINECRAFT_WEBHOOK_TOKEN` پیکربندی شود.
- **دسترسی کارکنان باز نمی‌شود:** نقش حساب را در پنل Owner/Developer بررسی کنید؛ ثبت‌نام به‌تنهایی نقش کارکنان نمی‌دهد.
