"""Intelligence Collector Daemon — continuous vector store population.

Fetches all intelligence sources in parallel and stores results in the
Qdrant vector store. Runs independently of the MCP server and dashboard,
ensuring data accumulates 24/7 for semantic search and historical analysis.

When WORLD_INTEL_SHARED_BRIDGE is configured, every successful high-level
observation is also appended to that NDJSON bridge with stable provenance and
fingerprint. This prevents reusable intelligence from existing only inside the
World Intel cache/vector store. The bridge is an intake/evidence stream, not a
parallel canonical conclusions store.

Usage:
    intel-collector                    # Single collection cycle
    intel-collector --daemon           # Run every 5 minutes
    intel-collector --interval 120     # Custom interval (seconds)
    intel-collector --sources markets,conflict  # Specific sources only
"""

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

logging.basicConfig(
    level=os.environ.get("WORLD_INTEL_LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("world-intel-collector")

from .cache import Cache
from .circuit_breaker import CircuitBreaker
from .fetcher import Fetcher
from .vector_store import VectorStore

# All fetchable sources grouped by domain.
# Each entry: (name, module_path, function_name, kwargs)
SOURCES = [
    # Markets (7)
    ("market_quotes", "sources.markets", "fetch_market_quotes", {}),
    ("crypto_quotes", "sources.markets", "fetch_crypto_quotes", {}),
    ("macro_signals", "sources.markets", "fetch_macro_signals", {}),
    ("sector_heatmap", "sources.markets", "fetch_sector_heatmap", {}),
    ("stablecoin_status", "sources.markets", "fetch_stablecoin_status", {}),
    ("etf_flows", "sources.markets", "fetch_etf_flows", {}),
    ("commodity_quotes", "sources.markets", "fetch_commodity_quotes", {}),
    ("btc_technicals", "sources.markets", "fetch_btc_technicals", {}),
    # Economic (6)
    ("energy_prices", "sources.economic", "fetch_energy_prices", {}),
    ("gas_prices", "sources.economic", "fetch_gas_prices", {}),
    ("residential_natgas", "sources.economic", "fetch_residential_natgas_prices", {}),
    ("electricity_rates", "sources.economic", "fetch_electricity_rates", {}),
    ("central_bank_rates", "sources.central_banks", "fetch_central_bank_rates", {}),
    # Natural Disasters (2)
    ("earthquakes", "sources.seismology", "fetch_earthquakes", {}),
    ("wildfires", "sources.wildfire", "fetch_wildfires", {}),
    # Conflict & Security (4)
    ("acled_events", "sources.conflict", "fetch_acled_events", {}),
    ("ucdp_events", "sources.conflict", "fetch_ucdp_events", {}),
    ("displacement", "sources.displacement", "fetch_displacement_summary", {}),
    # Military (2)
    ("military_flights", "sources.military", "fetch_military_flights", {}),
    # Infrastructure (4)
    ("internet_outages", "sources.infrastructure", "fetch_internet_outages", {}),
    ("cable_health", "sources.infrastructure", "fetch_cable_health", {}),
    ("service_status", "sources.service_status", "fetch_service_status", {}),
    # Maritime (1)
    ("nav_warnings", "sources.maritime", "fetch_nav_warnings", {}),
    # Climate (1)
    ("climate_anomalies", "sources.climate", "fetch_climate_anomalies", {}),
    # News (2)
    ("news_feed", "sources.news", "fetch_news_feed", {}),
    ("trending_keywords", "sources.news", "fetch_trending_keywords", {}),
    # Prediction (1)
    ("prediction_markets", "sources.prediction", "fetch_prediction_markets", {}),
    # Aviation (2)
    ("airport_delays", "sources.aviation", "fetch_airport_delays", {}),
    ("domestic_flights", "sources.aviation", "fetch_domestic_flights", {}),
    # Cyber (1)
    ("cyber_threats", "sources.cyber", "fetch_cyber_threats", {}),
    # Space Weather (1)
    ("space_weather", "sources.space_weather", "fetch_space_weather", {}),
    # AI/Tech (1)
    ("ai_watch", "sources.ai_watch", "fetch_ai_watch", {}),
    # Health (1)
    ("disease_outbreaks", "sources.health", "fetch_disease_outbreaks", {}),
    # Elections (1)
    ("election_calendar", "sources.elections", "fetch_election_calendar", {}),
    # Shipping (1)
    ("shipping_index", "sources.shipping", "fetch_shipping_index", {}),
    # Social (1)
    ("social_signals", "sources.social", "fetch_social_signals", {}),
    # Nuclear (1)
    ("nuclear_monitor", "sources.nuclear", "fetch_nuclear_monitor", {}),
    # Traffic (2)
    ("traffic_flow", "sources.traffic", "fetch_traffic_flow", {}),
    ("traffic_incidents", "sources.traffic", "fetch_traffic_incidents", {}),
    # Analysis (cross-domain, runs after raw sources)
    ("risk_scores", "sources.intelligence", "fetch_risk_scores", {}),
    ("signal_convergence", "sources.intelligence", "fetch_signal_convergence", {}),
    ("alert_digest", "analysis.alerts", "fetch_alert_digest", {}),
    ("weekly_trends", "analysis.alerts", "fetch_weekly_trends", {}),
    ("strategic_posture", "analysis.posture", "fetch_strategic_posture", {}),
    ("fleet_report", "sources.fleet", "fetch_fleet_report", {}),
    ("usni_fleet", "sources.usni_fleet", "fetch_usni_fleet", {}),
]

# Domain name → list of source names for --sources filtering
DOMAIN_GROUPS = {
    "markets": [
        "market_quotes",
        "crypto_quotes",
        "macro_signals",
        "sector_heatmap",
        "stablecoin_status",
        "etf_flows",
        "commodity_quotes",
        "btc_technicals",
    ],
    "economic": [
        "energy_prices",
        "gas_prices",
        "residential_natgas",
        "electricity_rates",
        "central_bank_rates",
    ],
    "natural": ["earthquakes", "wildfires"],
    "conflict": ["acled_events", "ucdp_events", "displacement"],
    "military": ["military_flights"],
    "infrastructure": ["internet_outages", "cable_health", "service_status"],
    "maritime": ["nav_warnings"],
    "climate": ["climate_anomalies"],
    "news": ["news_feed", "trending_keywords"],
    "prediction": ["prediction_markets"],
    "aviation": ["airport_delays", "domestic_flights"],
    "cyber": ["cyber_threats"],
    "space": ["space_weather"],
    "ai": ["ai_watch"],
    "health": ["disease_outbreaks"],
    "elections": ["election_calendar"],
    "shipping": ["shipping_index"],
    "social": ["social_signals"],
    "nuclear": ["nuclear_monitor"],
    "traffic": ["traffic_flow", "traffic_incidents"],
    "analysis": [
        "risk_scores",
        "signal_convergence",
        "alert_digest",
        "weekly_trends",
        "strategic_posture",
        "fleet_report",
        "usni_fleet",
    ],
}


def _resolve_source_filter(source_filter: str | None) -> set[str] | None:
    """Resolve --sources argument to a set of source names."""
    if not source_filter:
        return None
    names: set[str] = set()
    for part in source_filter.split(","):
        part = part.strip()
        if part in DOMAIN_GROUPS:
            names.update(DOMAIN_GROUPS[part])
        else:
            names.add(part)
    return names


def _import_fetch_fn(module_path: str, fn_name: str):
    """Dynamically import a fetch function from world_intel_mcp."""
    import importlib

    full_module = f"world_intel_mcp.{module_path}"
    mod = importlib.import_module(full_module)
    return getattr(mod, fn_name)


def _emit_shared_bridge(source_name: str, data) -> bool:
    """Append one successful observation to the configured shared NDJSON intake.

    The bridge is intentionally optional so upstream users are unaffected. It is
    append-only and preserves raw source payload plus deterministic fingerprint.
    Promotion/deduplication into canonical Signals/CCI remains downstream policy.
    """
    configured = os.environ.get("WORLD_INTEL_SHARED_BRIDGE", "").strip()
    if not configured:
        return False

    path = Path(configured).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical_payload = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(
        (source_name + "\n" + canonical_payload).encode("utf-8")
    ).hexdigest()
    record = {
        "schema": "world-intel-observation.v1",
        "source_system": "world-intel-mcp",
        "source_name": source_name,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "payload": data,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return True


async def collect_once(
    fetcher: Fetcher,
    vector_store: VectorStore,
    source_filter: set[str] | None = None,
    timeout: float = 45.0,
) -> dict:
    """Run one collection cycle across all sources.

    Returns dict with counts of successes, failures, and skipped.
    """
    start = time.time()
    sources_to_run = [
        s for s in SOURCES if source_filter is None or s[0] in source_filter
    ]

    async def _fetch_one(name: str, module_path: str, fn_name: str, kwargs: dict):
        try:
            fn = _import_fetch_fn(module_path, fn_name)
            result = await asyncio.wait_for(fn(fetcher, **kwargs), timeout=timeout)
            return name, result, None
        except asyncio.TimeoutError:
            return name, None, f"timeout ({timeout}s)"
        except Exception as exc:
            return name, None, str(exc)[:120]

    tasks = [_fetch_one(name, mod, fn, kw) for name, mod, fn, kw in sources_to_run]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes = 0
    failures = 0
    bridge_writes = 0
    errors = []

    for item in results:
        if isinstance(item, Exception):
            failures += 1
            errors.append(str(item)[:100])
            continue
        name, data, error = item
        if error:
            failures += 1
            errors.append(f"{name}: {error}")
            logger.warning("Collect %s failed: %s", name, error)
        elif data is not None:
            successes += 1
            # The fetcher already stores in vector_store via its hook,
            # but for sources that return composite data (analysis modules),
            # we also store the high-level result directly.
            if not isinstance(data, dict) or not data.get("error"):
                await vector_store.store(name, data)
                try:
                    if _emit_shared_bridge(name, data):
                        bridge_writes += 1
                except Exception as exc:
                    # Shared promotion must be observable, but it must not destroy
                    # World Intel's independent collection capability.
                    logger.warning("Shared bridge write failed for %s: %s", name, exc)
                    errors.append(f"{name}: shared_bridge:{str(exc)[:80]}")
        else:
            failures += 1

    elapsed = time.time() - start
    stats = await vector_store.collection_stats()

    summary = {
        "cycle_time_s": round(elapsed, 1),
        "sources_attempted": len(sources_to_run),
        "successes": successes,
        "failures": failures,
        "errors": errors[:10],
        "vector_store_points": stats.get("points_count", 0),
        "shared_bridge_configured": bool(os.environ.get("WORLD_INTEL_SHARED_BRIDGE", "").strip()),
        "shared_bridge_writes": bridge_writes,
    }

    logger.info(
        "Collection cycle: %d/%d sources in %.1fs, %d vector points, %d shared bridge writes",
        successes,
        len(sources_to_run),
        elapsed,
        stats.get("points_count", 0),
        bridge_writes,
    )

    return summary


async def run_daemon(
    interval: int = 300,
    source_filter: str | None = None,
) -> None:
    """Run collector continuously until interrupted."""
    cache = Cache()
    circuit_breaker = CircuitBreaker()
    vector_store = VectorStore()
    fetcher = Fetcher(cache=cache, circuit_breaker=circuit_breaker, vector_store=vector_store)

    stop_event = asyncio.Event()

    def _stop(*_args):
        logger.info("Shutdown requested")
        stop_event.set()

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _stop)
        loop.add_signal_handler(signal.SIGINT, _stop)
    except NotImplementedError:
        pass

    resolved_filter = _resolve_source_filter(source_filter)
    logger.info(
        "Collector daemon started (interval=%ss, sources=%s)",
        interval,
        sorted(resolved_filter) if resolved_filter else "all",
    )

    try:
        while not stop_event.is_set():
            try:
                await collect_once(fetcher, vector_store, resolved_filter)
            except Exception:
                logger.exception("Collection cycle failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await fetcher.close()
        except Exception:
            pass
        try:
            await vector_store.close()
        except Exception:
            pass


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="World Intelligence Collector")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=300, help="Daemon interval seconds")
    parser.add_argument("--sources", type=str, default=None, help="Comma-separated sources/domains")
    parser.add_argument("--timeout", type=float, default=45.0, help="Per-source timeout seconds")
    args = parser.parse_args()

    if args.daemon:
        asyncio.run(run_daemon(args.interval, args.sources))
        return

    async def _single():
        cache = Cache()
        circuit_breaker = CircuitBreaker()
        vector_store = VectorStore()
        fetcher = Fetcher(cache=cache, circuit_breaker=circuit_breaker, vector_store=vector_store)
        try:
            summary = await collect_once(
                fetcher,
                vector_store,
                _resolve_source_filter(args.sources),
                args.timeout,
            )
            print(json.dumps(summary, indent=2, sort_keys=True))
            if summary["failures"]:
                sys.exit(1)
        finally:
            try:
                await fetcher.close()
            except Exception:
                pass
            try:
                await vector_store.close()
            except Exception:
                pass

    asyncio.run(_single())


if __name__ == "__main__":
    main()
