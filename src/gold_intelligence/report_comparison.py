"""Compare verified saved reports without attributing changes to market events."""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, JsonValue, model_validator

from . import __version__
from .brief import NAMES, cell
from .models import Contract, Hash, Timestamp
from .research_report import LABELS, STATES, ResearchReport, load_verified_report
from .storage import canonical

Section = Literal["quality", "price", "macro", "calendar", "monthly", "releases", "revisions"]
ARTIFACTS = {"comparison.json", "comparison.fa.md", "inputs/before.json", "inputs/after.json"}
ID_FIELDS = {"record_id", "document_record_id", "record_ids"}
EVIDENCE_FIELDS = ID_FIELDS | {
    "capture_id",
    "before_capture_id",
    "after_capture_id",
    "candidate_capture_ids",
    "raw_sha256",
    "retrieved_at",
    "available_at",
    "captured_at",
    "evidence_captured_at",
}
AGE_FIELDS = {"age_hours", "reference_age_days", "evidence_age_hours"}
COLLECTIONS = {
    "summary": "خلاصه",
    "streams": "پوشش جریان",
    "issues": "مسائل کیفیت",
    "entries": "شاخص کلان",
    "upcoming": "رویداد تقویم",
    "levels": "سطح ماهانه",
    "changes": "تغییر ماهانه",
    "associations": "رابطهٔ ماهانه",
    "rolling": "پنجرهٔ متحرک",
    "documents": "سند",
    "values": "مقدار سند",
    "document_slots": "جایگاه سند",
    "captures": "ثبت سند",
    "pairs": "جفت اصلاحیه",
    "capture_changes": "تغییر ثبت سند",
}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def pointer(parent, key):
    return parent + "/" + str(key).replace("~", "~0").replace("/", "~1")


class FieldChange(Contract):
    path: str
    category: Literal["result", "evidence", "age"]
    before_present: bool
    after_present: bool
    before: JsonValue
    after: JsonValue


class EntityChange(Contract):
    section: Section
    collection: str
    identity: tuple[str | None, ...]
    label: str
    action: Literal["added", "removed", "modified"]
    before_pointer: str | None
    after_pointer: str | None
    fields: tuple[FieldChange, ...] = Field(min_length=1)


class SectionComparison(Contract):
    key: Section
    before_status: str
    after_status: str
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    modified: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    evidence_ids_added: tuple[Hash, ...]
    evidence_ids_removed: tuple[Hash, ...]


class ReportReference(Contract):
    location: str
    report_sha256: Hash
    fingerprint: Hash
    as_of: Timestamp
    generated_at: Timestamp
    software_version: str
    status: str


class ReportComparison(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    comparator_version: Literal["1.0.0"] = "1.0.0"
    software_version: str
    generated_at: Timestamp
    fingerprint: Hash
    before: ReportReference
    after: ReportReference
    status: Literal["unchanged", "context_only", "changed"]
    context_changes: tuple[FieldChange, ...]
    sections: tuple[SectionComparison, ...]
    changes: tuple[EntityChange, ...]
    daily_backtest_ready: Literal[False] = False
    causal_attribution: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self):
        if self.after.as_of < self.before.as_of:
            raise ValueError("after cutoff must not precede before cutoff")
        if tuple(s.key for s in self.sections) != tuple(LABELS):
            raise ValueError("comparison must contain all seven sections in order")
        keys = [(c.section, c.collection, c.identity) for c in self.changes]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate changed entity")
        for section in self.sections:
            for action in ("added", "removed", "modified"):
                count = sum(c.section == section.key and c.action == action for c in self.changes)
                if getattr(section, action) != count:
                    raise ValueError("section counts differ from changes")
        expected = (
            "changed" if self.changes else "context_only" if self.context_changes else "unchanged"
        )
        if self.status != expected:
            raise ValueError("comparison status differs from evidence")
        if self.fingerprint != comparison_fingerprint(self.model_dump(mode="json")):
            raise ValueError("comparison fingerprint mismatch")
        return self


def comparison_fingerprint(data):
    # Input byte hashes bind the exact source snapshots; output location is incidental.
    data = {k: v for k, v in data.items() if k not in {"generated_at", "fingerprint"}}
    for key in ("before", "after"):
        data[key] = {k: v for k, v in data[key].items() if k != "location"}
    return digest(canonical(data).encode())


def normalized(value):
    if isinstance(value, dict):
        return {
            k: sorted(v) if k in {"record_ids", "candidate_capture_ids"} else normalized(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def fields(before, after, path="", before_present=True, after_present=True):
    if before_present and after_present and before == after:
        return []
    if before_present and after_present and isinstance(before, dict) and isinstance(after, dict):
        return [
            change
            for key in sorted(before.keys() | after.keys())
            for change in fields(
                before.get(key), after.get(key), pointer(path, key), key in before, key in after
            )
        ]
    key = path.rsplit("/", 1)[-1]
    category = "age" if key in AGE_FIELDS else "evidence" if key in EVIDENCE_FIELDS else "result"
    return [
        FieldChange(
            path=path,
            category=category,
            before_present=before_present,
            after_present=after_present,
            before=before,
            after=after,
        )
    ]


def record_ids(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ID_FIELDS:
                found.update(child if isinstance(child, list) else [child] if child else [])
            else:
                found.update(record_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(record_ids(child))
    # Quality issues can contain non-hash diagnostic IDs; they are not record evidence.
    return {
        v
        for v in found
        if isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)
    }


def entities(report):
    """Index semantic rows; pointers always address the original input JSON."""
    data = report.model_dump(mode="json")
    result = {}

    def add(section, collection, identity, value, location):
        key = (section, collection, tuple(identity))
        if key in result:
            raise ValueError(f"ambiguous entity identity in {section}/{collection}")
        result[key] = (normalized(value), location)

    def rows(section, collection, keys):
        for index, row in enumerate(data[section][collection]):
            add(
                section, collection, [row[k] for k in keys], row, f"/{section}/{collection}/{index}"
            )

    omitted = {
        "quality": {"streams", "issues", "policy_sha256"},
        "macro": {"entries"},
        "calendar": {"upcoming", "horizon_days", "max_evidence_age_hours"},
        "monthly": {"levels", "changes", "associations", "rolling", "plan"},
        "releases": {"documents"},
        "revisions": {"document_slots", "captures", "pairs", "capture_changes", "plan"},
    }
    metadata = {"schema_version", "software_version", "as_of", "generated_at", "fingerprint"}
    for section, excluded in omitted.items():
        add(
            section,
            "summary",
            (),
            {k: v for k, v in data[section].items() if k not in excluded | metadata},
            f"/{section}",
        )
    price_ids = set()
    for index, stream in enumerate(data["quality"]["streams"]):
        identity = stream["identity"]
        price = (
            identity.get("kind") in {"price_close", "price_bar"}
            and identity.get("instrument") == "XAUUSD"
            and identity.get("timeframe") == "1d"
        )
        section = "price" if price else "quality"
        if price:
            price_ids.add(stream["stream_id"])
        add(section, "streams", [stream["stream_id"]], stream, f"/quality/streams/{index}")
    # Several missing required streams may share a code and no stream ID. Keep every issue.
    for index, issue in enumerate(data["quality"]["issues"]):
        add(
            "price" if issue["stream_id"] in price_ids else "quality",
            "issues",
            [issue["code"], issue["severity"], issue["stream_id"], issue["message"]],
            issue,
            f"/quality/issues/{index}",
        )
    rows("macro", "entries", ("series_id", "unit", "frequency"))
    rows("calendar", "upcoming", ("series_id", "reference_period", "timing_basis"))
    rows("monthly", "levels", ("series_id", "month", "unit", "method"))
    rows("monthly", "changes", ("month", "method"))
    rows("monthly", "associations", ("series_id", "population", "method"))
    rows("monthly", "rolling", ("series_id", "method", "last_month"))
    for index, document in enumerate(data["releases"]["documents"]):
        identity = [document[k] for k in ("source_url", "metric", "headline_period")]
        location = f"/releases/documents/{index}"
        add(
            "releases",
            "documents",
            identity,
            {k: v for k, v in document.items() if k != "values"},
            location,
        )
        for j, value in enumerate(document["values"]):
            add(
                "releases",
                "values",
                [*identity, value["reference_period"], value["unit"]],
                value,
                f"{location}/values/{j}",
            )
    rows("revisions", "document_slots", ("metric", "headline_period"))
    rows("revisions", "captures", ("capture_id",))
    rows("revisions", "pairs", ("metric", "reference_period"))
    rows(
        "revisions",
        "capture_changes",
        ("metric", "reference_period", "before_capture_id", "after_capture_id"),
    )
    return result


def context(report):
    data = report.model_dump(mode="json")
    return {k: data[k] for k in ("as_of", "software_version", "registry_sha256", "settings")}


def reference(report, content, location):
    return ReportReference(
        location=location,
        report_sha256=digest(content),
        **{
            key: getattr(report, key)
            for key in ("fingerprint", "as_of", "generated_at", "software_version", "status")
        },
    )


def entity_label(collection, identity, value):
    if collection == "streams":
        stream = value["identity"]
        parts = [stream.get(k) for k in ("source_id", "dataset", "venue")]
        return " / ".join(str(p) for p in parts if p) + f" [{identity[0][:12]}]"
    if collection == "issues":
        return value["code"] + " / " + (value["stream_id"] or "کل پایگاه")[:12]
    if collection == "captures":
        doc = value["evidence"]
        return f"{doc['release_id']} / {doc['headline_period']} / {doc['captured_at']}"
    if collection in {"documents", "values"}:
        return " / ".join(v for v in identity[1:] if v is not None)
    return " / ".join(NAMES.get(v, v) if v is not None else "نامشخص" for v in identity) or "کل بخش"


def compare_snapshots(
    before_bytes,
    after_bytes,
    before_location="",
    after_location="",
    software_version=__version__,
    generated_at=None,
):
    before = ResearchReport.model_validate_json(before_bytes)
    after = ResearchReport.model_validate_json(after_bytes)
    if after.as_of < before.as_of:
        raise ValueError("after cutoff must not precede before cutoff")
    old, new = entities(before), entities(after)
    changes, counts = [], defaultdict(lambda: defaultdict(int))
    evidence = {s: [set(), set()] for s in LABELS}
    for side, source in enumerate((old, new)):
        for (section, _, _), (value, _) in source.items():
            evidence[section][side].update(record_ids(value))
    for key in sorted(old.keys() | new.keys(), key=canonical):
        previous, current = old.get(key), new.get(key)
        changed = fields(
            previous[0] if previous else None,
            current[0] if current else None,
            before_present=previous is not None,
            after_present=current is not None,
        )
        action = "added" if previous is None else "removed" if current is None else "modified"
        counts[key[0]][action if changed else "unchanged"] += 1
        if changed:
            changes.append(
                EntityChange(
                    section=key[0],
                    collection=key[1],
                    identity=key[2],
                    label=entity_label(key[1], key[2], current[0] if current else previous[0]),
                    action=action,
                    before_pointer=previous[1] if previous else None,
                    after_pointer=current[1] if current else None,
                    fields=changed,
                )
            )
    states = [{s.key: s.status for s in r.sections} for r in (before, after)]
    sections = tuple(
        SectionComparison(
            key=s,
            before_status=states[0][s],
            after_status=states[1][s],
            **{k: counts[s][k] for k in ("added", "removed", "modified", "unchanged")},
            evidence_ids_added=sorted(evidence[s][1] - evidence[s][0]),
            evidence_ids_removed=sorted(evidence[s][0] - evidence[s][1]),
        )
        for s in LABELS
    )
    context_changes = fields(context(before), context(after))
    payload = dict(
        schema_version="1.0.0",
        comparator_version="1.0.0",
        software_version=software_version,
        generated_at=(generated_at or datetime.now(UTC)).isoformat(),
        before=reference(before, before_bytes, before_location).model_dump(mode="json"),
        after=reference(after, after_bytes, after_location).model_dump(mode="json"),
        status="changed" if changes else "context_only" if context_changes else "unchanged",
        context_changes=[f.model_dump(mode="json") for f in context_changes],
        sections=[s.model_dump(mode="json") for s in sections],
        changes=[c.model_dump(mode="json") for c in changes],
        daily_backtest_ready=False,
        causal_attribution=False,
    )
    return ReportComparison.model_validate(
        {**payload, "fingerprint": comparison_fingerprint(payload)}
    )


def display(value, present=True, age=False):
    if not present:
        return "ردیف/فیلد موجود نیست"
    if value is None:
        return "مقدار نامعلوم (null)"
    if age and isinstance(value, float):
        return f"≈ {value:.3f}"
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return cell(text if len(text) <= 140 else text[:137] + "…")


def preview_fields(row):
    changes = list(row.fields)
    if len(changes) == 1 and changes[0].path == "" and row.action != "modified":
        root = changes[0]
        value = root.after if root.after_present else root.before
        if isinstance(value, dict):
            changes = [
                FieldChange(
                    path=pointer("", key),
                    category="result",
                    before_present=root.before_present,
                    after_present=root.after_present,
                    before=child if root.before_present else None,
                    after=child if root.after_present else None,
                )
                for key, child in value.items()
            ]
    priorities = {
        name: i
        for i, name in enumerate(
            (
                "status",
                "eligible_records",
                "excluded_by_time",
                "compared_pairs",
                "vintage_matched_pairs",
                "changed_display_pairs",
                "value",
                "document_value",
                "difference_pp",
                "release_id",
                "headline_period",
                "reference_period",
                "unique_observations",
                "record_versions",
                "first_observed_at",
                "last_observed_at",
                "code",
                "message",
            )
        )
    }
    return sorted(
        changes,
        key=lambda f: (
            {"result": 0, "evidence": 1, "age": 2}[f.category],
            priorities.get(f.path.rsplit("/", 1)[-1], 99),
            f.path,
        ),
    )[:4]


def render_comparison(comparison):
    state = {
        "unchanged": "بدون تفاوت در محتوای مقایسه‌شده",
        "context_only": "فقط زمینهٔ محاسبه تغییر کرده است",
        "changed": "تفاوت ثبت شده است",
    }
    lines = [
        "# مقایسهٔ دو گزارش پژوهش طلا",
        "",
        f"**{state[comparison.status]}**",
        "",
        "| گزارش | زمان برش | نسخه | وضعیت گزارش |",
        "| --- | --- | --- | --- |",
    ]
    for label, ref in (("قبل", comparison.before), ("بعد", comparison.after)):
        lines.append(
            f"| {label} | {ref.as_of.isoformat()} | {cell(ref.software_version)} | {ref.status} |"
        )
    lines += ["", "## زمینهٔ محاسبه", ""]
    if comparison.context_changes:
        lines += [
            "زمان برش، تنظیمات، نسخه یا رجیستری منابع متفاوت است. تفاوت خروجی به‌تنهایی "
            "اثر مستقل هیچ‌کدام را اندازه نمی‌گیرد.",
            "",
            "| مورد | قبل | بعد |",
            "| --- | --- | --- |",
        ]
        for change in comparison.context_changes:
            lines.append(
                f"| {cell(change.path)} | {display(change.before, change.before_present)} | "
                f"{display(change.after, change.after_present)} |"
            )
    else:
        lines.append("زمان برش، تنظیمات، نسخهٔ نرم‌افزار و رجیستری منابع یکسان‌اند.")
    lines += [
        "",
        "## خلاصهٔ هفت بخش",
        "",
        "تعدادها مربوط به ردیف‌های معنایی گزارش‌اند؛ شمارش معامله، مشاهدهٔ مستقل یا "
        "رکورد تازهٔ پایگاه نیستند. شناسه‌های شاهد فقط موارد ارجاع‌شده در این بخش را پوشش می‌دهند.",
        "",
        "| بخش | وضعیت قبل ← بعد | افزوده | حذف از نما | تغییر | بدون تغییر | شاهد افزوده/حذف |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in comparison.sections:
        lines.append(
            f"| {LABELS[s.key]} | {STATES[s.before_status]} ← {STATES[s.after_status]} | "
            f"{s.added} | {s.removed} | {s.modified} | {s.unchanged} | "
            f"{len(s.evidence_ids_added)}/{len(s.evidence_ids_removed)} |"
        )
    age_changes = sum(f.category == "age" for c in comparison.changes for f in c.fields)
    lines += [
        "",
        f"{age_changes} فیلد سن داده یا شاهد تغییر کرده است. تغییر سن با جلو رفتن برش، "
        "بدون دریافت دادهٔ جدید هم رخ می‌دهد.",
        "",
    ]
    for section in comparison.sections:
        rows = sorted(
            (c for c in comparison.changes if c.section == section.key),
            key=lambda c: (
                all(f.category == "age" for f in c.fields),
                {
                    "summary": 0,
                    "pairs": 1,
                    "values": 2,
                    "streams": 3,
                    "documents": 4,
                    "document_slots": 5,
                    "issues": 6,
                    "captures": 7,
                }.get(c.collection, 8),
            ),
        )
        if not rows:
            continue
        lines += [
            f"## {LABELS[section.key]} — جزئیات منتخب",
            "",
            f"{len(rows)} ردیف متفاوت؛ حداکثر ۱۲ ردیف و ۴ فیلد هر ردیف اینجا نمایش داده می‌شود. "
            "تمام اختلاف‌ها و مسیر شاهد در [JSON مقایسه](comparison.json) موجود است.",
            "",
            "| مورد و هویت | نوع | فیلد | قبل | بعد |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in rows[:12]:
            label = f"{COLLECTIONS[row.collection]}: {row.label}"
            action = {"added": "افزوده به نما", "removed": "حذف از نما", "modified": "تغییر"}[
                row.action
            ]
            for f in preview_fields(row):
                lines.append(
                    f"| {cell(label)} | {action} | {cell(f.path or 'ردیف مقایسه‌شده')} | "
                    f"{display(f.before, f.before_present, f.category == 'age')} | "
                    f"{display(f.after, f.after_present, f.category == 'age')} |"
                )
        lines.append("")
    lines += [
        "## تفسیر و شواهد",
        "",
        "- سن داده در صفحه با علامت ≈ تا سه رقم اعشار گرد شده است؛ مقدار دقیق در JSON می‌ماند.",
        "- ورود یا خروج از نما می‌تواند نتیجهٔ برش، افق تقویم، برنامه یا انتخاب نسخه باشد؛ "
        "حذف از پایگاه یا انتشار جدید منبع از آن نتیجه نمی‌شود.",
        "- شناسهٔ شاهد با زمان دریافت و منشأ هم عوض می‌شود؛ تغییر شناسه لزوماً تغییر عدد نیست.",
        "- قیمت روزانه در این بسته فقط خلاصهٔ پوشش دارد. یکسانی پوشش، یکسانی تمام قیمت‌ها "
        "یا تمام رکوردهای پایگاه را ثابت نمی‌کند.",
        "- تغییر روش یا واحد، هویت ردیف را عوض می‌کند. تغییر اعضای نمونهٔ همبستگی نیز "
        "کنار ضریب حفظ می‌شود؛ اختلاف ضریب اثر خالص بازار نیست.",
        "- زمان ساخت و شناسه‌های مشتق گزارش، رویداد داده شمرده نمی‌شوند. هیچ اختلافی با "
        "صفر جایگزین و هیچ نسبت تغییر میان واحدها یا دوره‌های متفاوت محاسبه نشده است.",
        "- این مقایسه علت، غافلگیری بازار، اولین انتشار یا آمادگی بک‌تست را تأیید نمی‌کند.",
        "",
        "نسخهٔ کامل ورودی‌های بررسی‌شده: [قبل](inputs/before.json) و [بعد](inputs/after.json). "
        "مسیرهای before_pointer و after_pointer در JSON به همین دو ورودی اشاره می‌کنند.",
        "",
        "[فهرست و هش فایل‌ها](manifest.json) تغییر بایت‌ها را نسبت به فهرست می‌سنجد؛ "
        "امضای دیجیتال منبع نیست. verify-comparison مقایسه را از همین دو نسخه دوباره محاسبه می‌کند.",
        "",
        f"شناسهٔ مقایسه: `{comparison.fingerprint}`.",
        "",
    ]
    return "\n".join(lines)


class ComparisonFile(Contract):
    path: Literal["comparison.json", "comparison.fa.md", "inputs/before.json", "inputs/after.json"]
    sha256: Hash
    bytes: int = Field(ge=0)


class ComparisonManifest(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    fingerprint: Hash
    files: tuple[ComparisonFile, ...]

    @model_validator(mode="after")
    def complete(self):
        if len(self.files) != len(ARTIFACTS) or {f.path for f in self.files} != ARTIFACTS:
            raise ValueError("comparison manifest must contain the complete unique file set")
        return self


def compare_reports(before_dir, after_dir, output_dir):
    _, _, before = load_verified_report(before_dir)
    _, _, after = load_verified_report(after_dir)
    comparison = compare_snapshots(
        before, after, str(Path(before_dir).resolve()), str(Path(after_dir).resolve())
    )
    outputs = {
        "inputs/before.json": before,
        "inputs/after.json": after,
        "comparison.json": (comparison.model_dump_json(indent=2) + "\n").encode(),
        "comparison.fa.md": render_comparison(comparison).encode(),
    }
    manifest = ComparisonManifest(
        fingerprint=comparison.fingerprint,
        files=tuple(
            ComparisonFile(path=name, sha256=digest(content), bytes=len(content))
            for name, content in sorted(outputs.items())
        ),
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = uuid4().hex
    staging = output_dir / f".incomplete-{suffix}"
    staging.mkdir()
    (staging / "inputs").mkdir()
    for name, content in outputs.items():
        (staging / name).write_bytes(content)
    (staging / "manifest.json").write_bytes((manifest.model_dump_json(indent=2) + "\n").encode())
    verify_comparison(staging)
    destination = output_dir / f"comparison-{comparison.generated_at:%Y%m%dT%H%M%S%fZ}-{suffix[:8]}"
    staging.rename(destination)
    return comparison, destination


def verify_comparison(directory):
    directory = Path(directory).resolve()
    manifest = ComparisonManifest.model_validate_json((directory / "manifest.json").read_bytes())
    contents = {}
    for item in manifest.files:
        path = (directory / item.path).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("comparison artifact escaped its directory")
        content = path.read_bytes()
        if len(content) != item.bytes or digest(content) != item.sha256:
            raise ValueError("comparison artifact hash mismatch")
        contents[item.path] = content
    saved = ReportComparison.model_validate_json(contents["comparison.json"])
    if saved.fingerprint != manifest.fingerprint:
        raise ValueError("comparison manifest fingerprint mismatch")
    expected = compare_snapshots(
        contents["inputs/before.json"],
        contents["inputs/after.json"],
        saved.before.location,
        saved.after.location,
        saved.software_version,
        saved.generated_at,
    )
    if expected != saved:
        raise ValueError("comparison differs from recomputed input snapshots")
    return {
        "status": "verified",
        "files": len(contents),
        "fingerprint": saved.fingerprint,
        "comparison_status": saved.status,
    }
