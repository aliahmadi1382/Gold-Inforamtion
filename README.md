# Gold Market Intelligence

زیرساخت پژوهش و تحلیل بازار طلا، با منشأ قابل پیگیری برای هر مشاهده و کنترل زمان دسترسی به داده.
این مخزن از روی [متن ارسالی](docs/specification/original-brief.md) ساخته شده است.
نسخهٔ **۰٫۳٫۰** ورود قیمت پایانی روزانهٔ طلا از Alpha Vantage و دادهٔ کلان FRED را همراه ثبت منشأ و سنجش کیفیت فراهم می‌کند. نخستین دریافت واقعی در محیط محلی انجام شده است؛ داده و کلیدها در GitHub منتشر نمی‌شوند. [فازهای اجرایی](docs/phases.fa.md) و [آموزش فارسی](docs/education/README.fa.md) مسیر ادامه را مشخص می‌کنند.

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
