"""Deterministic, report-backed synthesis; no voting, prediction or causal attribution."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__
from .models import Contract, Hash, Timestamp, aware
from .research_report import load_verified_report, parse_research_report
from .storage import canonical

RULE_VERSION = "1.0.0"
FILES = {"synthesis.json", "synthesis.fa.md", "inputs/research.json"}
OUTCOMES = {
    "matches_display": "سازگار در دقت نمایش",
    "vintage_disagreement": "اختلاف با نسخهٔ هم‌تاریخ",
    "revision_difference": "اختلاف با نسخهٔ اصلاح‌شدهٔ جاری",
    "rounding_boundary": "مرز گردکردن؛ نتیجهٔ قطعی ندارد",
    "missing_period": "دورهٔ قابل مقایسه موجود نیست",
    "missing_value": "مقدار قابل مقایسه موجود نیست",
    "method_concordance": "جهت دو ضریب سازگار است",
    "method_disagreement": "جهت دو روش متفاوت است",
    "insufficient_sample": "شاهد آماری کافی نیست",
    "not_comparable": "تعریف یا دوره متفاوت؛ ادغام نمی‌شود",
    "coverage_limited": "پژوهش روزانه نیازمند شاهد بیشتر است",
    "no_evidence": "شاهد موجود نیست",
}


class Finding(Contract):
    id: str
    category: Literal["release", "monthly", "comparability", "readiness"]
    outcome: Literal[
        "matches_display",
        "vintage_disagreement",
        "revision_difference",
        "rounding_boundary",
        "missing_period",
        "missing_value",
        "method_concordance",
        "method_disagreement",
        "insufficient_sample",
        "not_comparable",
        "coverage_limited",
        "no_evidence",
    ]
    sources: tuple[
        Literal["bls", "fred", "world_bank_pink_sheet", "alpha_vantage_gold", "cftc_disaggregated"],
        ...,
    ]
    pointers: tuple[str, ...] = Field(min_length=1)
    facts: dict
    limitation: str


class EvidenceSynthesis(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    rule_version: Literal["1.0.0"] = RULE_VERSION
    software_version: str
    generated_at: Timestamp
    as_of: Timestamp
    input_sha256: Hash
    report_fingerprint: Hash
    status: Literal["limited", "needs_review", "no_evidence"]
    findings: tuple[Finding, ...]
    outcome_counts: dict[str, int]
    fingerprint: Hash
    daily_backtest_ready: Literal[False] = False
    market_direction: Literal["not_inferred"] = "not_inferred"
    confidence_probability: None = None

    @model_validator(mode="after")
    def consistent(self):
        if len({finding.id for finding in self.findings}) != len(self.findings):
            raise ValueError("duplicate synthesis finding identity")
        counts = {outcome: sum(f.outcome == outcome for f in self.findings) for outcome in OUTCOMES}
        if self.outcome_counts != counts:
            raise ValueError("synthesis counts differ from findings")
        payload = self.model_dump(mode="json", exclude={"fingerprint", "generated_at"})
        if self.fingerprint != hashlib.sha256(canonical(payload).encode()).hexdigest():
            raise ValueError("synthesis fingerprint mismatch")
        return self


def resolve_pointer(data, pointer):
    value = data
    if not pointer.startswith("/"):
        raise ValueError("evidence pointer must be absolute")
    for key in pointer[1:].split("/"):
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def association_outcome(association, minimum_pairs):
    enough = (
        association.status == "estimated"
        and association.n >= minimum_pairs
        and association.n == len(set(association.months)) == len(association.months)
        and association.pearson is not None
        and association.spearman is not None
    )
    if not enough:
        return "insufficient_sample"
    p_sign = (association.pearson > 0) - (association.pearson < 0)
    s_sign = (association.spearman > 0) - (association.spearman < 0)
    return "method_disagreement" if p_sign != s_sign else "method_concordance"


def build_synthesis(content, *, generated_at=None, software_version=None):
    report = parse_research_report(content)
    data = json.loads(content)
    findings = []

    def add(identifier, category, outcome, sources, pointers, facts, limitation):
        for pointer in pointers:
            resolve_pointer(data, pointer)
        findings.append(
            Finding(
                id=identifier,
                category=category,
                outcome=outcome,
                sources=sources,
                pointers=pointers,
                facts=facts,
                limitation=limitation,
            )
        )

    for i, document in enumerate(report.releases.documents):
        for j, value in enumerate(document.values):
            base = f"/releases/documents/{i}/values/{j}"
            for kind in ("release_date_vintage", "current_revision"):
                comparison = getattr(value, kind)
                outcome = comparison.status
                if outcome == "differs_display":
                    outcome = (
                        "vintage_disagreement"
                        if kind == "release_date_vintage"
                        else "revision_difference"
                    )
                add(
                    f"release:{i}:{j}:{kind}",
                    "release",
                    outcome,
                    ("bls", "fred"),
                    (base, f"/releases/documents/{i}"),
                    dict(
                        metric=document.metric,
                        release_id=document.release_id,
                        source_url=str(document.source_url),
                        announced_at=document.announced_at.isoformat(),
                        captured_at=document.captured_at.isoformat(),
                        period=value.reference_period,
                        period_role=value.period_role,
                        unit=value.unit,
                        document_value=value.document_value,
                        compared_value=comparison.value,
                        difference=comparison.difference_from_document,
                        vintage_date=str(comparison.vintage_date)
                        if comparison.vintage_date
                        else None,
                        comparison=kind,
                        transformation=comparison.transformation,
                        document_status=document.document_status,
                        record_ids=[value.document_record_id, *comparison.record_ids],
                    ),
                    "سند و FRED شاهد مستقل یک انتشار نیستند؛ هم‌تاریخی و برابری در دقت نمایش، "
                    "اولین انتشار یا ساعت تحویل را اثبات نمی‌کند. "
                    "اختلاف نسخهٔ جاری، غافلگیری بازار نیست.",
                )

    for i, association in enumerate(report.monthly.associations):
        if association.population != "common":
            continue
        outcome = association_outcome(association, report.monthly.plan.minimum_pairs)
        add(
            f"monthly:{i}",
            "monthly",
            outcome,
            ("world_bank_pink_sheet", "fred"),
            (f"/monthly/associations/{i}", "/monthly/plan", "/monthly/levels", "/monthly/changes"),
            dict(
                series_id=association.series_id,
                method=association.method,
                n=association.n,
                months=[str(month) for month in association.months],
                status=association.status,
                pearson=association.pearson,
                spearman=association.spearman,
            ),
            "دو ضریب روی همان نمونه‌اند؛ جهت سازگار، شاهد مستقل یا احتمال اطمینان نیست. "
            "روابط هم‌زمان و توصیفی‌اند؛ روش‌های قیمت و نمونه‌ها ادغام نمی‌شوند.",
        )

    price = [
        s for s in report.quality.streams if s.identity.get("source_id") == "alpha_vantage_gold"
    ]
    gold_levels = [
        level
        for level in report.monthly.levels
        if level.series_id == "WB_GOLD_MONTHLY" and level.record_ids
    ]
    add(
        "comparability:gold",
        "comparability",
        "not_comparable" if price and gold_levels else "no_evidence",
        ("alpha_vantage_gold", "world_bank_pink_sheet"),
        ("/quality/streams", "/monthly/levels"),
        dict(daily_price_streams=len(price), monthly_gold_levels=len(gold_levels)),
        "قیمت پایانی تاریخ‌دار Alpha Vantage و میانگین ماهانهٔ World Bank دو تعریف متفاوت دارند؛ "
        "اختلاف سطح آن‌ها خطای منبع یا اختلاف قیمت قابل معامله شمرده نمی‌شود.",
    )
    references = [
        dict(
            series_id=e.series_id,
            reference_at=e.reference_at.isoformat() if e.reference_at else None,
            status=e.status,
            max_age_days=e.max_age_days,
        )
        for e in report.macro.entries
    ]
    pointers = ["/macro/entries"]
    sources = ["fred"]
    cot_date = None
    if report.schema_version == "2.0.0":
        pointers.append("/positioning/weeks")
        sources.append("cftc_disaggregated")
        cot_date = (
            str(max(w.observed_date for w in report.positioning.weeks))
            if report.positioning.weeks
            else None
        )
    add(
        "comparability:periods",
        "comparability",
        "not_comparable"
        if any(e.reference_at for e in report.macro.entries) or cot_date
        else "no_evidence",
        tuple(sources),
        tuple(pointers),
        dict(macro_references=references, cot_reference=cot_date),
        "برش مشترک، دورهٔ مرجع مشترک نیست. "
        "COT هفتگی، شاخص روزانه و شاخص ماهانه رأی‌های مستقل هم‌زمان نیستند؛ "
        "از آن‌ها جهت بازار یا امتیاز اطمینان ساخته نمی‌شود.",
    )
    add(
        "readiness:daily",
        "readiness",
        "coverage_limited",
        (),
        ("/daily_backtest_ready", "/first_release_verified", "/quality/issues"),
        dict(
            daily_backtest_ready=report.daily_backtest_ready,
            first_release_verified=report.first_release_verified,
            issue_codes=sorted({issue.code for issue in report.quality.issues}),
        ),
        "تعریف واحد و جلسهٔ قیمت، دادهٔ قابل مقایسه و زمان واقعی انتشار "
        "باید پیش از پژوهش روزانه تأیید شوند؛ این جمع‌بندی دروازه‌ها را تغییر نمی‌دهد.",
    )
    counts = {outcome: sum(f.outcome == outcome for f in findings) for outcome in OUTCOMES}
    status = (
        "needs_review"
        if counts["vintage_disagreement"] or counts["method_disagreement"]
        else "limited"
    )
    if (
        not report.releases.documents
        and not any(level.record_ids for level in report.monthly.levels)
        and not any(e.reference_at for e in report.macro.entries)
        and not cot_date
        and not price
    ):
        status = "no_evidence"
    payload = dict(
        schema_version="1.0.0",
        rule_version=RULE_VERSION,
        software_version=software_version or __version__,
        generated_at=aware(generated_at or datetime.now(UTC))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        as_of=report.as_of.isoformat().replace("+00:00", "Z"),
        input_sha256=hashlib.sha256(content).hexdigest(),
        report_fingerprint=report.fingerprint,
        status=status,
        findings=[f.model_dump(mode="json") for f in findings],
        outcome_counts=counts,
        daily_backtest_ready=False,
        market_direction="not_inferred",
        confidence_probability=None,
    )
    canonical_payload = {k: v for k, v in payload.items() if k != "generated_at"}
    return EvidenceSynthesis(
        **payload, fingerprint=hashlib.sha256(canonical(canonical_payload).encode()).hexdigest()
    )


def render_synthesis(synthesis):
    lines = [
        "# جمع‌بندی شواهد چندمنبعی",
        "",
        f"برش: `{synthesis.as_of.isoformat()}`؛ وضعیت: `{synthesis.status}`؛ "
        f"قواعد: `{synthesis.rule_version}`.",
        "",
        "این جمع‌بندی از گزارش ذخیره‌شده بازحساب می‌شود؛ "
        "تعداد یافته‌ها شمار منابع مستقل یا احتمال اطمینان نیست.",
        "",
    ]
    for finding in synthesis.findings:
        lines += [
            f"## {OUTCOMES[finding.outcome]}",
            "",
            f"شناسه: `{finding.id}`؛ منابع: {', '.join(finding.sources) or 'دروازهٔ گزارش'}.",
            "",
            "```json",
            json.dumps(finding.facts, ensure_ascii=False, indent=2),
            "```",
            "",
            finding.limitation,
            "",
            "شاهد در ورودی همراه: " + ", ".join(f"`{p}`" for p in finding.pointers),
            "",
        ]
    return "\n".join(lines) + "\n"


class SynthesisFile(Contract):
    path: Literal["synthesis.json", "synthesis.fa.md", "inputs/research.json"]
    sha256: Hash
    bytes: int = Field(ge=0)


class SynthesisManifest(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    fingerprint: Hash
    files: tuple[SynthesisFile, ...]


def write_synthesis(report_directory, output_dir):
    _, _, content = load_verified_report(report_directory)
    synthesis = build_synthesis(content)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    staging = output_dir / f".incomplete-{token}"
    (staging / "inputs").mkdir(parents=True)
    outputs = {
        "synthesis.json": (synthesis.model_dump_json(indent=2) + "\n").encode(),
        "synthesis.fa.md": render_synthesis(synthesis).encode(),
        "inputs/research.json": content,
    }
    manifest = SynthesisManifest(
        fingerprint=synthesis.fingerprint,
        files=tuple(
            SynthesisFile(path=name, sha256=hashlib.sha256(value).hexdigest(), bytes=len(value))
            for name, value in sorted(outputs.items())
        ),
    )
    for name, value in outputs.items():
        (staging / name).write_bytes(value)
    (staging / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    verify_synthesis(staging)
    destination = output_dir / f"synthesis-{synthesis.generated_at:%Y%m%dT%H%M%S%fZ}-{token[:8]}"
    staging.rename(destination)
    return synthesis, destination


def verify_synthesis(directory):
    directory = Path(directory).resolve()
    manifest = SynthesisManifest.model_validate_json((directory / "manifest.json").read_bytes())
    if len(manifest.files) != len(FILES) or {f.path for f in manifest.files} != FILES:
        raise ValueError("synthesis manifest requires the exact unique file set")
    contents = {}
    for item in manifest.files:
        path = directory / item.path
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError("synthesis input escaped its bundle")
        content = path.read_bytes()
        if len(content) != item.bytes or hashlib.sha256(content).hexdigest() != item.sha256:
            raise ValueError("synthesis artifact hash mismatch")
        contents[item.path] = content
    saved = EvidenceSynthesis.model_validate_json(contents["synthesis.json"])
    expected = build_synthesis(
        contents["inputs/research.json"],
        generated_at=saved.generated_at,
        software_version=saved.software_version,
    )
    if saved != expected or manifest.fingerprint != saved.fingerprint:
        raise ValueError("synthesis differs from recomputed report evidence")
    if contents["synthesis.fa.md"] != render_synthesis(expected).encode():
        raise ValueError("synthesis prose differs from recomputed evidence")
    return dict(status="verified", fingerprint=saved.fingerprint, findings=len(saved.findings))
