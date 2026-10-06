# Gold Market Intelligence

زیرساخت پژوهش و تحلیل بازار طلا، با منشأ قابل پیگیری برای هر مشاهده و کنترل زمان دسترسی به داده.
این مخزن از روی [متن ارسالی](docs/specification/original-brief.md) ساخته شده است.
نسخهٔ **۰٫۱۳٫۰** دریافت منابع و ساخت گزارش را با یک دستور دستی انجام می‌دهد. نتیجهٔ هر منبع، خطای دریافت، سن داده و ورودی‌های نیازمند بازبینی دستی جدا دیده می‌شوند. شکست یک منبع پنهان نمی‌شود؛ دریافت‌های موفق و گزارش‌های قبلی حفظ می‌شوند. گزارش هشت‌بخشی و مقایسهٔ نسخه‌ها همچنان در دسترس‌اند. داده و کلیدها در GitHub منتشر نمی‌شوند. [فازهای اجرایی](docs/phases.fa.md) و [آموزش فارسی](docs/education/README.fa.md) مسیر ادامه را مشخص می‌کنند.

## اجرای سریع

Python 3.11 یا بالاتر و [uv](https://docs.astral.sh/uv/getting-started/installation/) لازم است.
دستورها را در ریشهٔ مخزن اجرا کنید:

```sh
uv sync --frozen
uv run gold validate-registry
uv run gold demo
uv run gold --store local/demo audit
uv run gold --store local/demo quality --as-of 2024-04-22T22:00:00Z --allow-synthetic --output local/demo/quality.json
uv run pytest
```

خروجی نمونه در `local/demo/snapshot.json` ساخته می‌شود. تمام ۸۰ کندل نمونه **مصنوعی** هستند؛ قیمت واقعی یا توصیهٔ خریدوفروش نیستند. اجرای دوبارهٔ دمو رکورد تکراری ایجاد نمی‌کند. برای مشاهدهٔ گزینه‌ها: `uv run gold --help`.

برای به‌روزرسانی واقعی با فایل کلید محلیِ از قبل آماده‌شده:

```sh
uv run gold --credentials-file local/credentials.env refresh-report
```

فایل فارسی مسیر `summary` نتیجهٔ دریافت‌ها و تازگی را نشان می‌دهد و به گزارش پژوهش پیوند دارد. [فصل چهاردهم](docs/education/14-manual-refresh.fa.md) اجرای معمول، وضعیت ناقص و ورودی‌های دستی را توضیح می‌دهد.

## امکانات پیاده‌سازی‌شده

- ثبت دادهٔ خام با SHA-256 و نگهداری تراکنشی مشاهدات و نسخه‌ها در SQLite.
- ورود CSV قیمت با کنترل OHLC، واحد حجم، نوع ابزار، سررسید آتی و منطقهٔ زمانی.
- دریافت صفحه‌بندی‌شدهٔ FRED با کلید API و انتخاب vintage؛ ورود CSV سالانهٔ CFTC Legacy Futures Only.
- دریافت تاریخچهٔ روزانهٔ `XAUUSD` از Alpha Vantage در قرارداد مستقل `price_close`؛ حفظ تاریخ‌های منبع بدون ساختن OHLC.
- جداسازی زمان مشاهده، زمان دسترسی و زمان دریافت برای تحلیل تاریخی بدون استفاده از اطلاعات آینده.
- SMA20/50، مومنتوم، ATR، نوسان، شکست محدوده و ساختار سقف/کف تأییدشده.
- خروجی ساخت‌یافتهٔ وضعیت بازار با شناسهٔ شواهد، داده‌های مفقود، تازگی قیمت و تفکیک دادهٔ مصنوعی.
- مطالعهٔ پنجرهٔ رویداد: بازده، بیشترین رشد/افت، drawdown و زمان بازگشت در پنجرهٔ مشاهده‌شده.
- قراردادهای JSON Schema برای داده، خبر، تقویم، رویداد تاریخی و خروجی تحلیل؛ کنترل مجوز بازنشر.
- ثبت موفقیت/شکست هر ورود CLI همراه هش دادهٔ خام، شناسهٔ رکورد و تعداد درج؛ مرور با `gold runs`.
- گزارش پوشش هر جریان، اصلاحیه‌ها، مقادیر مفقود، تازگی، شکاف‌های نیازمند بررسی و خطاهای منشأ با `gold quality`.
- بارگذاری صریح کلیدها از فایل محلی و آموزش فارسی مفاهیم بازار، زمان داده و راه‌اندازی منابع رایگان.
- دریافت گروهی هفت شاخص FRED با کنترل واحد، بسامد و تعدیل فصلی پیش از ورود؛ گزارش شکست مستقل هر سری.
- انتخاب نسخهٔ مجاز هر شاخص در `macro-context` بدون استفاده از اطلاعات آینده یا پرکردن مقدار مفقود.
- خواندن ماهانهٔ Pink Sheet، حفظ تغییر روش در ژوئن ۲۰۲۵ و مقایسهٔ توصیفی ماهانه با قیمت‌های روزانه.
- تقویم بررسی‌شدهٔ CPI/اشتغال، تبدیل زمان نیویورک/UTC/تهران و گزارش فارسی وضعیت داده.
- پژوهش ماهانهٔ چهار رابطه با نمونه‌های دقیق، کنترل اصلاحیه و مفقودی، گزارش فارسی/JSON و تطبیق مستقل محاسبات.
- ورود مقدارهای سند رسمی با شماره، دوره، واحد و وضعیت بازانتشار؛ تطبیق با FRED همان تاریخ و تفکیک اختلاف نسخه‌ها.
- دفتر اصلاحیه در پنجرهٔ ثابت، جدول پوشش مورد انتظار، تشخیص سند مبهم و حفظ تاریخچهٔ ثبت‌های همان سند.
- گزارش پژوهش یکپارچه از یک وضعیت ثابت پایگاه و یک زمان برش، با خلاصهٔ هشت بخش و حفظ کمبودها؛ بررسی بسته با `gold verify-report`.
- مقایسهٔ دو گزارش بررسی‌شده با هویت ردیف، تفکیک زمینه/سن/شاهد، نگهداری ورودی‌ها و محاسبهٔ دوباره با `gold verify-comparison`.
- دریافت COT تفکیکی طلای COMEX با `fetch-cftc-gold` و گزارش پنج گروه، خالص، نسبت به OI و تغییر هفت‌روزه با `positioning-context`؛ کنترل کامل صفحه‌ها و جمع هر دو سمت.
- دریافت و گزارش با `refresh-report`، ثبت مرحله، نتیجهٔ مستقل هر سری، بازهٔ هم‌پوشان، کنترل اجرای هم‌زمان و خلاصهٔ فارسی تازگی؛ مدارک BLS و vintageهای مشخص دستی باقی می‌مانند.

## راهنمای پروژه

| سند | کاربرد |
| --- | --- |
| [Master specification](docs/specification/master-specification.md) | نیازمندی‌های هر ده لایه، فازها و تصمیم‌های باز |
| [Coverage matrix](docs/specification/coverage-matrix.md) | چه چیزی اجرا شده و چه چیزی به توسعه یا دسترسی نیاز دارد |
| [Architecture](docs/architecture.md) | اجزا، مسیر داده و تفاوت با ساختار پیشنهادی اولیه |
| [Data contracts](docs/source-methodology/data-contracts.md) | دانه‌بندی، واحدها، زمان، نسخه و lineage |
| [Source audit](docs/source-methodology/source-audit.md) | راستی‌آزمایی و اصلاح ادعاهای فایل اولیه |
| [Operations](docs/operations.md) | نصب، ورود دادهٔ واقعی، FRED، CFTC، خروجی و عیب‌یابی |
| [عملیات کیفیت](docs/quality-operations.md) | گزارش ورود، سیاست کیفیت و کدهای خروج |
| [فازهای اجرایی](docs/phases.fa.md) | وضعیت مراحل و تصمیم‌های تأییدشدهٔ شما |
| [آموزش فارسی](docs/education/README.fa.md) | فصل‌های آموزشی، تمرین و واژه‌نامه |
| [Market history](docs/market-history/README.md) | تفکیک دوره‌های تاریخی بدون اتصال مصنوعی سری‌ها |
| [Research methods](docs/trading-methodology/README.md) | حدود تحلیل، اعتبارسنجی و شروط مراحل بعد |
| [Roadmap](docs/roadmap.md) | معیار اتمام هر مرحله و وابستگی‌ها |
| [Licenses](sources/licenses.md) | دسترسی عمومی، مجوز استفاده، بازنشر و آموزش مدل |

## دادهٔ واقعی و وضعیت فعلی

[تحویل ۰٫۱۳](docs/source-methodology/manual-refresh.fa.md) عملیات دریافت و گزارش را با یک فرمان متصل می‌کند. در اجرای واقعی، ۹ دریافت موفق و دریافت COT با HTTP 403 ناموفق بود؛ گزارش با دادهٔ قبلی COT ساخته شد و وضعیت کل صریحاً `partial` ماند. [فصل چهاردهم](docs/education/14-manual-refresh.fa.md) راهنمای اجرای این مسیر است.

[تحویل ۰٫۱۲](docs/source-methodology/integrated-positioning.fa.md) گزارش هشت‌بخشی، بستهٔ دارای ۱۳ خروجی فهرست‌شده و مقایسهٔ COT با هویت تاریخ/گروه را اضافه می‌کند. نسخه‌های قدیمی با منطق خودشان بررسی می‌شوند. [فصل سیزدهم](docs/education/13-integrated-positioning.fa.md) تفاوت قالب قدیمی، دادهٔ مفقود، دادهٔ قدیمی و تغییر شاهد را توضیح می‌دهد.

[تحویل ۰٫۱۱](docs/source-methodology/cot-positioning.fa.md) شامل ۱٬۰۶۰ تاریخ مشاهده و ۵٬۳۰۰ رکورد COT از ژوئن ۲۰۰۶ تا سپتامبر ۲۰۲۶ است. همه با پاسخ خام تطبیق شدند؛ تاریخ‌های غیرسه‌شنبه و فاصله‌های نامنظم حفظ شده‌اند. زمان انتشار تاریخی همچنان نامعلوم و دسترسی محدود به زمان دریافت است. [فصل دوازدهم](docs/education/12-cot-positioning.fa.md) گروه‌ها، اسپرد، OI، خالص و حدود تفسیر آن‌ها را توضیح می‌دهد.

[تحویل ۰٫۱۰](docs/source-methodology/report-comparison.fa.md) با `compare-reports` تغییر محتوای گزارش را از تغییر صرف زمینهٔ محاسبه جدا نمایش می‌دهد. دریافت دوباره، حذف از نما و تغییر قیمت یکی تلقی نمی‌شوند؛ مقایسهٔ قیمت روزانه محدود به پوشش موجود در گزارش است. [فصل یازدهم](docs/education/11-comparing-research-runs.fa.md) هویت ردیف، شاهد، مقدار و حدود انتساب علت را توضیح می‌دهد.

[تحویل ۰٫۹](docs/source-methodology/unified-research-report.fa.md) با `research-report` خروجی‌های پژوهشی را در یک بستهٔ فارسی/JSON متصل می‌کند. گزارش از داده‌های موجود ساخته می‌شود و گزارش قبلی را بازنویسی نمی‌کند. بررسی Manifest، هش و سازگاری اجزا در `verify-report` انجام می‌شود؛ این بررسی تأیید اصالت ناشر یا صحت اقتصادی داده نیست. [فصل دهم](docs/education/10-unified-research-report.fa.md) راهنمای خواندن و بازتولید آن است.

[تحویل ۰٫۸](docs/source-methodology/revision-ledger.fa.md) با `revision-ledger` برای ژانویه تا ژوئن ۲۰۲۰، ۱۲ مقایسه از ۱۴ سند CPI/اشتغال می‌سازد. شواهد مفقود یا مبهم از مخرج پوشش حذف نمی‌شوند؛ بازانتشارها و محدودیت دقت نمایش آشکارند. [فصل نهم](docs/education/09-revision-ledger.fa.md) روش خواندن دفتر و تفاوت اصلاحیه، تغییر ماهانه و ثبت دوبارهٔ سند را توضیح می‌دهد.

[تحویل ۰٫۷](docs/source-methodology/release-values.fa.md) با `release-value-report` اتصال سند و نسخه را بررسی می‌کند. چهار سند CPI/اشتغال و نسخه‌های تاریخی متناظر وارد شدند. ساعت سرصفحه، زمان واقعی تحویل تلقی نشده و زمان دسترسی مشاهدات قدیمی بازنویسی نشده است. [فصل هشتم](docs/education/08-release-values-and-vintages.fa.md) انتشار اولیه، بازانتشار، دقت نمایش و Surprise را توضیح می‌دهد.

[تحویل ۰٫۶](docs/source-methodology/monthly-research.fa.md) با `monthly-research` از داده‌های موجود پژوهش ماهانه می‌سازد. نسخه‌های شناخته‌شده در زمان برش، پژوهش توصیفی را پشتیبانی می‌کنند؛ این خروجی بک‌تست تاریخی یا سیگنال معامله نیست. [فصل هفتم](docs/education/07-monthly-relationships.fa.md) راهنمای مفاهیم و خواندن نتیجه است.

[تحویل ۰٫۵](docs/source-methodology/release-evidence.fa.md) مستقل از پاسخ ارائه‌دهندهٔ قیمت پیش رفت: `research-brief` گزارش فارسی و JSON می‌سازد؛ تقویم، یادداشت بازبینی صفحات رسمی است و زمان اعلام‌شده را به انتشار واقعی یا دسترسی تاریخی مقدار تبدیل نمی‌کند. [فصل ششم](docs/education/06-release-calendar-and-reports.fa.md) راهنمای خواندن گزارش است.

[نتیجهٔ فاز ۳](docs/source-methodology/history-acquisition.fa.md): تاریخچه و تطبیق با خام انجام شده، کیفیت کلی «هشدار» است. روش قیمت‌های آخر هفته و ساعت مرجع روزانه هنوز تأیید نشده‌اند؛ مقایسهٔ ماهانه مجوز ورود به بک‌تست نیست. [فصل پنجم آموزش](docs/education/05-history-macro-and-revisions.fa.md) تفاوت دوره، انتشار، vintage و دریافت را توضیح می‌دهد.

این نسخه دادهٔ تجاری، اخبار کامل، کلید API یا سوابق ساختگی بازار را منتشر نمی‌کند.
مسیر انتخاب‌شدهٔ کاربر API رایگان Alpha Vantage برای قیمت پایانی و FRED برای متغیرهای کلان است. هر دو اتصال در ۲۰۲۶-۱۰-۰۵ با کلید شخصی آزموده شدند. [راهنمای دریافت](docs/operations.md) و [نتیجه و محدودیت‌های فاز ۲](docs/source-methodology/first-acquisition.fa.md) را ببینید. قیمت پایانی به‌تنهایی OHLC کامل نیست؛ دستور `snapshot` همچنان به کندل کامل نیاز دارد.
ورود CSV دارای منشأ و حق استفاده نیز پشتیبانی می‌شود. برای LBMA/IBA، CME، WGC و خوراک خبر، دسترسی و مجوز هر مجموعه باید جداگانه ثبت شود.
گزارش COT روز مشاهده و روز انتشار متفاوت دارد؛ زمان انتشار ناشناخته به زمان دریافت محدود می‌شود.

انتخاب تأییدشده، تحلیل روزانهٔ XAU/USD با منابع رایگان و عمومی و سپس توسعه به بازه‌های کوتاه‌تر است. تاریخچه از قدیمی‌ترین شواهد معتبر، در دوره‌های جدا، طراحی شده است. کارگزار و حدود ریسک هنوز انتخاب نشده‌اند. هیچ اتصال سفارش‌گذاری وجود ندارد و خروجی تصمیم در این فاز `NO_TRADE` است.

## Repository layout

```text
src/gold_intelligence/   Executable adapters, contracts, storage, analysis and CLI
config/                 Project defaults and macro series shortlist
sources/                Source registry, rights policy and provenance guidance
schemas/                Generated, versioned JSON Schemas
docs/                   Specification, history, methodology and operating guide
data/events/            Cited historical milestones and unverified research candidates
examples/               Clearly synthetic input and output
tests/                  Offline integrity, time, adapter and CLI tests
scripts/                Repository publication checks
.github/workflows/      Linux and Windows CI
local/                  Ignored local raw data, databases and output
```

Technical documentation and code use English identifiers for interoperability. All external data remain subject to their provider terms; no open-source license for the project code has been selected by the owner yet.

This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.
