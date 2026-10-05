"""Explicit, scoped loading of supported API keys; no shell expansion or value logging."""

import os
import re
from contextlib import contextmanager
from pathlib import Path

ALLOWED_KEYS = {"FRED_API_KEY", "ALPHAVANTAGE_API_KEY"}


@contextmanager
def credential_environment(path: Path | None):
    values = {}
    if path is not None:
        content = path.read_bytes()
        if len(content) > 16_384:
            raise ValueError("credentials file exceeds the 16 KiB limit")
        for number, line in enumerate(content.decode("utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or key not in ALLOWED_KEYS or key in values:
                raise ValueError(f"unsupported or duplicate credentials entry at line {number}")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise ValueError(f"invalid API key format at line {number}")
            values[key] = value
    overrides = {key: value for key, value in values.items() if value}
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
