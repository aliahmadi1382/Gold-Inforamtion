from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, HttpUrl, model_validator

from .models import Contract, Layer, LicenseStatus, NonEmpty, Record


class Source(Contract):
    source_id: NonEmpty
    provider: NonEmpty
    url: HttpUrl
    layers: tuple[Layer, ...] = Field(min_length=1)
    access: Literal["public", "api_key", "licensed", "manual"]
    license_status: LicenseStatus
    license_id: NonEmpty
    terms_url: HttpUrl
    redistribution_allowed: bool = False
    training_allowed: bool = False
    implementation: Literal["implemented", "manual_import", "planned", "synthetic"]
    coverage: NonEmpty
    frequency: NonEmpty
    notes: NonEmpty

    @model_validator(mode="after")
    def restricted_rights(self):
        if self.license_status == "RESTRICTED" and (
            self.redistribution_allowed or self.training_allowed
        ):
            raise ValueError("restricted sources cannot grant redistribution/training rights")
        return self


class Registry(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    reviewed_on: NonEmpty
    sources: tuple[Source, ...]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [source.source_id for source in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("source IDs must be unique")
        return self

    def get(self, source_id: str) -> Source:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise ValueError(f"source not registered: {source_id}")


def load_registry(path: Path) -> Registry:
    return Registry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def validate_record_source(record: Record, registry: Registry) -> Source:
    source = registry.get(record.provenance.source_id)
    p = record.provenance
    if (
        p.license_id != source.license_id
        or p.license_status != source.license_status
        or p.provider != source.provider
    ):
        raise ValueError("record provenance does not match source registry")
    if p.synthetic != (source.implementation == "synthetic"):
        raise ValueError("record synthetic flag does not match registry")
    layer = (
        record.layer
        if record.kind == "observation"
        else {
            "price_bar": "price",
            "positioning": "positioning",
            "news_event": "news",
            "calendar_release": "calendar",
        }[record.kind]
    )
    if layer not in source.layers:
        raise ValueError("record layer does not match source registry")
    return source


def export_public(records: list[Record], registry: Registry, path: Path) -> int:
    # Check the entire batch first. No partial export, no record-level permission override.
    for record in records:
        source = registry.get(record.provenance.source_id)
        if not source.redistribution_allowed:
            raise ValueError(f"redistribution not approved: {source.source_id}")
        validate_record_source(record, registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(record.model_dump_json() + "\n")
    return len(records)
