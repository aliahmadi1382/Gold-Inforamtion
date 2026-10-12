"""Manual, single-request GoldAPI evidence capture; no store writes or orders."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .goldapi_review import review_goldapi
from .models import aware

ENDPOINT = "https://www.goldapi.io/api/price/XAU/USD"
LIMIT = 1_048_576


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("provider redirect rejected")


def fetch_quote(key):
    request = Request(ENDPOINT, headers={"x-access-token": key, "Accept": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("provider response exceeds capture limit")
            return raw, response.status
    except HTTPError as exc:
        raise ValueError(f"provider HTTP status {exc.code}; no retry") from None
    except (URLError, OSError):
        raise ValueError("provider connection failed; no retry") from None


def capture_goldapi(root, key, fetch=fetch_quote, now=lambda: datetime.now(UTC)):
    if not isinstance(key, str) or not key.strip() or any(c in key for c in "\r\n"):
        raise ValueError("configured GoldAPI key required")
    started = aware(now()).astimezone(UTC)
    folder = Path(root) / started.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    receipt = dict(
        endpoint=ENDPOINT,
        started_at=started.isoformat(),
        attempts=1,
        status="failed",
        trading_eligible=False,
    )
    try:
        raw, status = fetch(key)
        received = aware(now()).astimezone(UTC)
        if not isinstance(raw, bytes) or len(raw) > LIMIT or received < started:
            raise ValueError("invalid response or receipt clock")
        receipt.update(http_status=status, received_at=received.isoformat())
        (folder / "raw.json").write_bytes(raw)
        receipt["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        if status != 200:
            raise ValueError("provider did not return HTTP 200")
        review = review_goldapi(raw, received)
        (folder / "quote-review.json").write_text(
            review.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        receipt["status"] = "metadata_checked_not_trading_eligible"
    except (ValueError, OSError):
        raise ValueError("capture failed; inspect private receipt; no retry") from None
    finally:
        (folder / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return folder
