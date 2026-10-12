"""Receipt-time shadow signals on verified real captures; delayed marks never fill orders."""

import hashlib
from datetime import datetime
from statistics import mean

from pydantic import Field

from .forward_dataset import build_forward_dataset
from .models import Contract
from .storage import canonical


class ShadowSettings(Contract):
    initial_cash: float = Field(default=10000, gt=0)
    lookback: int = Field(default=20, ge=2, le=250, strict=True)
    maximum_age_seconds: int = Field(default=60, ge=0, le=900, strict=True)
    maximum_gap_seconds: int = Field(default=86400, gt=0, strict=True)


def evaluate_shadow(root, settings=None, *, excluded_capture_ids=()):
    settings = ShadowSettings.model_validate((settings or ShadowSettings()).model_dump())
    dataset = build_forward_dataset(root, excluded_capture_ids=excluded_capture_ids)
    history, decisions = [], []
    previous_receipt, previous_source = None, None
    for row in dataset["observations"]:
        received = datetime.fromisoformat(row["received_at"])
        source = datetime.fromisoformat(row["source_at"])
        reason = None
        if previous_receipt is not None and received <= previous_receipt:
            reason = "nonadvancing_receipt"
        elif previous_source is not None and source <= previous_source:
            reason = "nonadvancing_source"
        elif row["age_at_receipt_seconds"] > settings.maximum_age_seconds:
            reason = "stale_quote"
        if previous_receipt is not None:
            if (received - previous_receipt).total_seconds() > settings.maximum_gap_seconds:
                history.clear()
        prior_count = len(history)
        reference = (
            mean(history[-settings.lookback :]) if len(history) >= settings.lookback else None
        )
        mid = row["bid"] / 2 + row["ask"] / 2
        signal = "blocked"
        if reason is None:
            if reference is None:
                reason, signal = "warming_up", "wait"
            else:
                reason = "comparison_with_prior_observations"
                signal = (
                    "buy_candidate"
                    if mid > reference
                    else "exit_candidate"
                    if mid < reference
                    else "hold"
                )
            history.append(mid)
        decisions.append(
            dict(
                capture_id=row["capture_id"],
                raw_sha256=row["raw_sha256"],
                decision_at=row["received_at"],
                source_at=row["source_at"],
                age_seconds=row["age_at_receipt_seconds"],
                reason=reason,
                signal=signal,
                prior_eligible_observations=prior_count,
                prior_mean=reference,
                cash=settings.initial_cash,
                quantity=0,
                orders_enabled=False,
            )
        )
        previous_receipt, previous_source = received, source
    identity = dict(
        engine_version="real-shadow-1", settings=settings.model_dump(mode="json"), dataset=dataset
    )
    return dict(
        schema_version="1.0.0",
        engine_version="real-shadow-1",
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        synthetic=False,
        scope="real_receipt_shadow_signals_only",
        settings=settings.model_dump(mode="json"),
        input_dataset=dataset,
        decisions=decisions,
        orders=[],
        fills=[],
        initial_cash=settings.initial_cash,
        final_cash=settings.initial_cash,
        final_quantity=0,
        realized_pnl=0,
        fees=0,
        orders_enabled=False,
        market_validation=False,
        broker_connected=False,
        performance_conclusion="not_established",
    )
