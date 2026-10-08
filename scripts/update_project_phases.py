"""Generate the Persian phase guide from the same contract consumed by the local UI."""

from pathlib import Path

from gold_intelligence.project_roadmap import load_project_roadmap

STATUSES = {
    "completed": "تکمیل‌شده",
    "partial": "بخشی تکمیل‌شده",
    "in_progress": "در حال توسعه",
    "blocked": "وابسته به پیش‌نیاز",
    "not_started": "شروع نشده",
}


def render(roadmap):
    lines = [
        "# مسیر و فازهای پروژه",
        "",
        "> این سند از `config/project_roadmap.json` ساخته می‌شود؛ "
        "همان مرجع در رابط لوکال نمایش داده می‌شود. پس از هر تحویل، "
        "وضعیت بخش مربوط به‌روز و سند دوباره ساخته می‌شود.",
        "",
        f"**نسخهٔ جاری: {roadmap.current_delivery} · فاز فعال: {roadmap.current_phase}**",
        "",
        f"**قدم بعد:** {roadmap.next_step}",
        "",
        "تکمیل یک تحویل به معنی تکمیل فاز مادر نیست. درصد کلی ساختگی ارائه نمی‌شود؛ "
        "معیار پایان و کارهای باز هر فاز پایین مشخص‌اند. پژوهش روزانه و بک‌تست "
        "به دروازه‌های قیمت و زمان انتشار وابسته‌اند. "
        "اجرای واقعی اختیاری است و مجوز جدا می‌خواهد.",
        "",
        "تصمیم‌های مالک: XAU/USD روزانه، بازه‌های کوتاه‌تر پس از آن، "
        "منابع رایگان و عمومی و آموزش فارسی همراه هر تحویل.",
        "",
        "| فاز | بخش | وضعیت | تحویل‌ها |",
        "|---|---|---|---|",
    ]
    for phase in roadmap.phases:
        lines.append(
            f"| {phase.id} | {phase.title} | {STATUSES[phase.status]} | {phase.releases} |"
        )
    for phase in roadmap.phases:
        lines += [
            "",
            f"## فاز {phase.id} — {phase.title}",
            "",
            f"**وضعیت:** {STATUSES[phase.status]}",
            "",
            f"**معیار پایان:** {phase.criterion}",
            "",
            "**تحویل‌شده:**",
            "",
        ]
        lines += [f"- {item}" for item in phase.delivered] or ["- هنوز تحویلی ندارد."]
        lines += ["", "**باقی‌مانده / پیش‌نیاز:**", ""]
        lines += [f"- {item}" for item in phase.remaining] or [
            "- در دامنهٔ تعریف‌شدهٔ این فاز مورد باز ندارد."
        ]
        if phase.deliveries:
            lines += ["", "| تحویل | قابلیت | وضعیت |", "|---|---|---|"]
            lines += [
                f"| {item.version} | {item.title} | {STATUSES[item.status]} |"
                for item in phase.deliveries
            ]
    lines += [
        "",
        "## مرور و اجرا",
        "",
        "رابط لوکال: `uv run gold --store local/market local-ui` سپس `http://127.0.0.1:8765`.",
        "",
        "[راهنمای رابط](source-methodology/local-workspace.fa.md) · "
        "[آموزش‌ها](education/README.fa.md) · "
        "[تاریخچهٔ فازبندی قبل از پنل](phases-history.fa.md)",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    Path("docs/phases.fa.md").write_text(
        render(load_project_roadmap("config/project_roadmap.json")), encoding="utf-8"
    )
