"""Personal commercial intelligence core.

This module is deliberately separate from the geopolitical dashboard. It only
emits factual source records backed by a live/cached source response and keeps
all derived scores explicitly marked as inference.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

DEFAULT_DB = Path.home() / ".world-intel" / "commercial.db"
USER_AGENT = "world-intel-commercial/0.1 (read-only research)"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def factual_record(
    source_id: str,
    source_url: str,
    payload: Any,
    *,
    stable_identifier: str = "",
    record_type: str = "source-response",
    permitted_use: str = "official/public source terms",
) -> dict[str, Any]:
    return {
        "record_kind": "factual-source-record",
        "provenance": {
            "source_id": source_id,
            "source_url": source_url,
            "retrieved_at": utcnow(),
            "permitted_use": permitted_use,
            "payload_sha256": canonical_hash(payload),
            "record_type": record_type,
            "stable_identifier": stable_identifier,
        },
        "raw": payload,
        "derived_signals": [],
    }


class CommercialStore:
    """Small local SQLite store for provenance-bearing observations/watchlist."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("COMMERCIAL_INTEL_DB") or DEFAULT_DB).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    stable_identifier TEXT NOT NULL DEFAULT '',
                    retrieved_at TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    UNIQUE(source_id, stable_identifier, payload_sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_observations_source_time
                    ON observations(source_id, retrieved_at DESC);
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(entity_type, external_id)
                );
                """
            )

    def save_record(self, record: dict[str, Any]) -> None:
        p = record["provenance"]
        with self._connect() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO observations
                (source_id, stable_identifier, retrieved_at, source_url,
                 payload_sha256, record_type, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p["source_id"],
                    p.get("stable_identifier", ""),
                    p["retrieved_at"],
                    p["source_url"],
                    p["payload_sha256"],
                    p["record_type"],
                    json.dumps(record["raw"], ensure_ascii=False, separators=(",", ":")),
                ),
            )

    def ledger(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, source_id, stable_identifier, retrieved_at, source_url,
                       payload_sha256, record_type
                FROM observations ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def watchlist(self) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, entity_type, external_id, label, created_at FROM watchlist ORDER BY id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_watch(self, entity_type: str, external_id: str, label: str = "") -> dict[str, Any]:
        entity_type = entity_type.strip().lower()
        external_id = external_id.strip()
        if not entity_type or not external_id:
            raise ValueError("entity_type and external_id are required")
        created_at = utcnow()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO watchlist(entity_type, external_id, label, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(entity_type, external_id) DO UPDATE SET label=excluded.label
                """,
                (entity_type, external_id, label.strip(), created_at),
            )
            row = con.execute(
                "SELECT id, entity_type, external_id, label, created_at FROM watchlist WHERE entity_type=? AND external_id=?",
                (entity_type, external_id),
            ).fetchone()
        return dict(row)


class SourceRegistry:
    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def configured(self, source_id: str) -> bool:
        if source_id == "companies_house":
            return bool(os.getenv("COMPANIES_HOUSE_API_KEY"))
        return True

    def mark_attempt(self, source_id: str) -> None:
        item = self._state.setdefault(source_id, {})
        item["last_attempt"] = utcnow()

    def mark_success(self, source_id: str) -> None:
        item = self._state.setdefault(source_id, {})
        item.update({"last_success": utcnow(), "status": "LIVE", "latest_error": None})

    def mark_failure(self, source_id: str, status: str, error: str) -> None:
        item = self._state.setdefault(source_id, {})
        item.update({"status": status, "latest_error": error[:200]})

    def snapshot(self) -> list[dict[str, Any]]:
        known = [
            "companies_house",
            "contracts_finder",
            "find_a_tender",
            "ons",
            "planning_data",
            "environment_agency",
            "ukri_gtr",
        ]
        out = []
        for source_id in known:
            state = dict(self._state.get(source_id, {}))
            configured = self.configured(source_id)
            if not configured:
                status = "MISSING_CREDENTIAL"
            else:
                status = state.get("status", "NOT_CHECKED")
            out.append(
                {
                    "source": source_id,
                    "configured": configured,
                    "last_attempt": state.get("last_attempt"),
                    "last_success": state.get("last_success"),
                    "status": status,
                    "latest_error": state.get("latest_error"),
                }
            )
        return out


SOURCE_REGISTRY = SourceRegistry()


async def fetch_json(
    source_id: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    SOURCE_REGISTRY.mark_attempt(source_id)
    request_headers = {"accept": "application/json", "user-agent": USER_AGENT, **(headers or {})}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=request_headers)
        if response.status_code in {403, 429}:
            SOURCE_REGISTRY.mark_failure(source_id, "RATE_LIMITED", f"HTTP {response.status_code}")
            raise RuntimeError(f"{source_id} rate limited or access throttled")
        response.raise_for_status()
        payload = response.json()
        SOURCE_REGISTRY.mark_success(source_id)
        return factual_record(source_id, url, payload)
    except httpx.TimeoutException as exc:
        SOURCE_REGISTRY.mark_failure(source_id, "FAILED", "timeout")
        raise RuntimeError(f"{source_id} timed out") from exc
    except (httpx.HTTPError, ValueError) as exc:
        SOURCE_REGISTRY.mark_failure(source_id, "FAILED", type(exc).__name__)
        raise RuntimeError(f"{source_id} request failed") from exc


def _window(days: int) -> tuple[str, str]:
    days = max(1, min(int(days), 90))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


async def fetch_contracts_finder(days: int = 14, limit: int = 100) -> dict[str, Any]:
    start, end = _window(days)
    params = [
        ("publishedFrom", start),
        ("publishedTo", end),
        ("stages", "tender"),
        ("stages", "award"),
        ("limit", str(max(1, min(limit, 100)))),
    ]
    url = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?" + urlencode(params)
    return await fetch_json("contracts_finder", url)


async def fetch_find_a_tender(days: int = 14, limit: int = 100) -> dict[str, Any]:
    start, end = _window(days)
    params = {
        "publishedFrom": start,
        "publishedTo": end,
        "stages": "tender,award",
        "limit": str(max(1, min(limit, 100))),
    }
    url = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?" + urlencode(params)
    return await fetch_json("find_a_tender", url)


async def search_companies(query: str, limit: int = 20) -> dict[str, Any]:
    key = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    if not key:
        SOURCE_REGISTRY.mark_failure("companies_house", "MISSING_CREDENTIAL", "credential not configured")
        return {"status": "MISSING_CREDENTIAL", "records": []}
    q = query.strip()
    if not q:
        return {"status": "EMPTY_QUERY", "records": []}
    params = urlencode({"q": q, "items_per_page": max(1, min(limit, 100))})
    url = "https://api.company-information.service.gov.uk/search/companies?" + params
    token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    record = await fetch_json("companies_house", url, headers={"authorization": f"Basic {token}"})
    return {"status": "LIVE", "records": [record]}


async def search_ons(query: str = "business economy investment", limit: int = 20) -> dict[str, Any]:
    params = urlencode({"q": query.strip() or "business economy investment", "content_type": "dataset,timeseries", "limit": max(1, min(limit, 100))})
    url = "https://api.beta.ons.gov.uk/v1/search?" + params
    return await fetch_json("ons", url)


async def fetch_planning(limit: int = 100) -> dict[str, Any]:
    d = (datetime.now(timezone.utc) - timedelta(days=30)).date()
    params = urlencode(
        [
            ("dataset", "planning-application"),
            ("start_date_year", d.year),
            ("start_date_month", d.month),
            ("start_date_day", d.day),
            ("start_date_match", "since"),
            ("limit", max(1, min(limit, 100))),
        ]
    )
    url = "https://www.planning.data.gov.uk/entity.json?" + params
    return await fetch_json("planning_data", url)


async def fetch_environment_agency() -> dict[str, Any]:
    return await fetch_json("environment_agency", "https://environment.data.gov.uk/flood-monitoring/id/floods")


async def search_ukri(query: str = "artificial intelligence automation", limit: int = 25) -> dict[str, Any]:
    params = urlencode({"term": query.strip() or "artificial intelligence automation", "fetchSize": max(1, min(limit, 100)), "page": 1})
    url = "https://gtr.ukri.org/api/search/project?" + params
    return await fetch_json("ukri_gtr", url, headers={"accept": "application/vnd.rcuk.gtr.json-v7"})


def _releases(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("releases"), list):
        return [r for r in payload["releases"] if isinstance(r, dict)]
    packages = payload.get("releasePackages") or payload.get("packages")
    if isinstance(packages, list):
        out: list[dict[str, Any]] = []
        for package in packages:
            if isinstance(package, dict) and isinstance(package.get("releases"), list):
                out.extend(r for r in package["releases"] if isinstance(r, dict))
        return out
    return []


def _supplier_name(release: dict[str, Any]) -> str:
    for award in release.get("awards") or []:
        for supplier in award.get("suppliers") or []:
            if supplier.get("name"):
                return str(supplier["name"])
    for party in release.get("parties") or []:
        if "supplier" in (party.get("roles") or []) and party.get("name"):
            return str(party["name"])
    return ""


def normalise_notice(release: dict[str, Any], source_id: str, evidence_hash: str) -> dict[str, Any]:
    tender = release.get("tender") or {}
    buyer = release.get("buyer") or {}
    awards = release.get("awards") or []
    award_value = 0.0
    for award in awards:
        try:
            award_value += float((award.get("value") or {}).get("amount") or 0)
        except (TypeError, ValueError):
            pass
    stable_id = str(release.get("ocid") or release.get("id") or evidence_hash)
    tags = release.get("tag") or []
    stage = str(tags[0] if tags else ("award" if awards else "tender"))
    return {
        "id": stable_id,
        "source": source_id,
        "title": tender.get("title") or "Untitled notice",
        "description": tender.get("description") or "",
        "buyer": buyer.get("name") or "",
        "supplier": _supplier_name(release),
        "published": release.get("date"),
        "stage": stage,
        "value": award_value or (tender.get("value") or {}).get("amount"),
        "currency": (tender.get("value") or {}).get("currency") or "GBP",
        "evidence_ref": evidence_hash,
    }


def supplier_momentum(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in notices:
        supplier = (row.get("supplier") or "").strip()
        if not supplier:
            continue
        bucket = grouped.setdefault(supplier, {"supplier": supplier, "awards": 0, "value": 0.0, "evidence_refs": []})
        if "award" in str(row.get("stage", "")).lower():
            bucket["awards"] += 1
        try:
            bucket["value"] += float(row.get("value") or 0)
        except (TypeError, ValueError):
            pass
        if row.get("evidence_ref"):
            bucket["evidence_refs"].append(row["evidence_ref"])

    results = []
    for item in grouped.values():
        award_points = min(70.0, item["awards"] * 20.0)
        value_points = min(30.0, max(0.0, math.log10(item["value"] + 1) - 4.0) * 7.5) if item["value"] else 0.0
        score = round(min(100.0, award_points + value_points), 1)
        results.append(
            {
                "signal_type": "supplier_momentum",
                "supplier": item["supplier"],
                "score": score,
                "is_inference": True,
                "explanation": f"Deterministic score from {item['awards']} observed award(s) and £{item['value']:,.0f} observed award value in the current window.",
                "evidence_refs": item["evidence_refs"][:25],
            }
        )
    return sorted(results, key=lambda x: x["score"], reverse=True)


def delivery_pressure(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    out = []
    for row in notices:
        if "award" not in str(row.get("stage", "")).lower():
            continue
        recency = 0.0
        raw_date = row.get("published")
        if raw_date:
            try:
                dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                days = max(0, (now - dt.astimezone(timezone.utc)).days)
                recency = max(0.0, 50.0 - min(days, 50))
            except ValueError:
                pass
        try:
            value = float(row.get("value") or 0)
        except (TypeError, ValueError):
            value = 0.0
        value_points = min(50.0, max(0.0, math.log10(value + 1) - 4.0) * 12.5) if value else 0.0
        score = round(min(100.0, recency + value_points), 1)
        out.append(
            {
                "signal_type": "post_award_delivery_pressure",
                "notice_id": row["id"],
                "supplier": row.get("supplier") or None,
                "buyer": row.get("buyer") or None,
                "score": score,
                "is_inference": True,
                "explanation": "Deterministic score based only on observed award recency and observed contract value; it is not a claim about supplier performance.",
                "evidence_refs": [row.get("evidence_ref")] if row.get("evidence_ref") else [],
            }
        )
    return sorted(out, key=lambda x: x["score"], reverse=True)
