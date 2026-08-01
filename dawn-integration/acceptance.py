#!/usr/bin/env python3
"""Offline acceptance runner for DAWN commercial signals."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SIGNAL_TYPES = {
    "company-event", "executive-change", "financial-pressure", "cyber-incident",
    "government-contract", "supply-chain-event", "infrastructure-event", "news-convergence",
}
USES = {"research-only", "meeting-preparation", "account-prioritisation", "draft-outreach-angle"}
SIGNAL_ID = re.compile(r"^SIG-[A-Z0-9-]{6,80}$")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def validate(signal: dict[str, Any], now: datetime) -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "signal_id", "account", "signal_type", "observed_at", "source", "summary", "confidence", "recommended_use", "external_actions_performed"}
    missing = sorted(required - signal.keys())
    if missing:
        errors.append(f"missing:{','.join(missing)}")
    if signal.get("schema_version") != 1:
        errors.append("schema_version")
    if not isinstance(signal.get("signal_id"), str) or not SIGNAL_ID.fullmatch(signal["signal_id"]):
        errors.append("signal_id")
    if signal.get("signal_type") not in SIGNAL_TYPES:
        errors.append("signal_type")
    if signal.get("recommended_use") not in USES:
        errors.append("recommended_use")
    confidence = signal.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence")
    observed = parse_time(signal.get("observed_at"))
    if observed is None:
        errors.append("observed_at")
    elif observed > now:
        errors.append("future_signal")
    elif (now - observed).days > 90:
        errors.append("stale_signal")
    source = signal.get("source") if isinstance(signal.get("source"), dict) else {}
    if not source.get("name") or not source.get("retrieved_at"):
        errors.append("source_provenance")
    parsed_url = urlparse(str(source.get("url", "")))
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        errors.append("source_url")
    retrieved = parse_time(source.get("retrieved_at"))
    if retrieved is None or (observed and retrieved < observed):
        errors.append("retrieval_time")
    summary = signal.get("summary")
    if not isinstance(summary, str) or not 20 <= len(summary) <= 5000:
        errors.append("summary")
    if signal.get("external_actions_performed") is not False:
        errors.append("external_actions")
    return errors


def evaluate(signal: dict[str, Any], now: datetime) -> dict[str, Any]:
    errors = validate(signal, now)
    return {
        "schema_version": 1,
        "capability": "dawn-commercial-intelligence",
        "operation": "validate-commercial-signal",
        "status": "blocked" if errors else "success",
        "evidence": [str(signal.get("source", {}).get("url", ""))] if not errors else [],
        "data": {"signal_accepted": not errors, "signal": signal if not errors else None},
        "warnings": errors,
        "cost": {"currency": "USD", "estimated": 0},
        "external_actions_performed": False,
    }


def main() -> int:
    now = datetime(2026, 8, 1, 7, 0, tzinfo=timezone.utc)
    valid = json.loads((ROOT / "fixtures" / "valid-signal.json").read_text())
    invalid = json.loads((ROOT / "fixtures" / "invalid-signal.json").read_text())
    accepted = evaluate(valid, now)
    refused = evaluate(invalid, now)
    assertions = [
        accepted["status"] == "success",
        accepted["data"]["signal_accepted"] is True,
        accepted["external_actions_performed"] is False,
        refused["status"] == "blocked",
        "stale_signal" in refused["warnings"],
        "source_url" in refused["warnings"],
    ]
    report = {
        "capability": "dawn-commercial-intelligence",
        "status": "passed" if all(assertions) else "failed",
        "tests": len(assertions),
        "passed": sum(assertions),
        "network_used": False,
        "credentials_required": False,
        "external_actions_performed": False,
    }
    print(json.dumps(report, indent=2))
    return 0 if all(assertions) else 1


if __name__ == "__main__":
    sys.exit(main())
