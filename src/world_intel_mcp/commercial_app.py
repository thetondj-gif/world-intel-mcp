"""Local/private Personal Commercial & Capital Intelligence web application."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from world_intel_mcp.commercial import (
    CommercialStore,
    SOURCE_REGISTRY,
    delivery_pressure,
    fetch_contracts_finder,
    fetch_environment_agency,
    fetch_find_a_tender,
    fetch_planning,
    normalise_notice,
    search_companies,
    search_ons,
    search_ukri,
    supplier_momentum,
)

_store: CommercialStore | None = None


def store() -> CommercialStore:
    global _store
    if _store is None:
        _store = CommercialStore()
    return _store


def _payload(record: dict[str, Any]) -> Any:
    return record.get("raw") if isinstance(record, dict) else None


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


async def _procurement(days: int = 14, query: str = "") -> dict[str, Any]:
    results = await asyncio.gather(
        fetch_contracts_finder(days=days),
        fetch_find_a_tender(days=days),
        return_exceptions=True,
    )
    notices: list[dict[str, Any]] = []
    source_errors: dict[str, str] = {}
    for source_id, result in zip(("contracts_finder", "find_a_tender"), results):
        if isinstance(result, Exception):
            source_errors[source_id] = str(result)
            continue
        store().save_record(result)
        evidence_hash = result["provenance"]["payload_sha256"]
        for release in _releases(_payload(result)):
            notices.append(normalise_notice(release, source_id, evidence_hash))
    q = query.strip().lower()
    if q:
        notices = [
            row
            for row in notices
            if q in " ".join(
                str(row.get(k) or "") for k in ("title", "description", "buyer", "supplier")
            ).lower()
        ]
    notices.sort(key=lambda row: str(row.get("published") or ""), reverse=True)
    return {
        "observed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "days": days,
        "query": query or None,
        "count": len(notices),
        "notices": notices[:200],
        "source_errors": source_errors,
        "signals": {
            "supplier_momentum": supplier_momentum(notices)[:30],
            "post_award_delivery_pressure": delivery_pressure(notices)[:30],
        },
    }


async def home(_request: Request) -> HTMLResponse:
    return HTMLResponse(HTML)


async def health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "personal-commercial-intelligence",
            "status": "ok",
            "mode": "local_private",
            "paid_calls_enabled": False,
            "database": str(store().path),
        }
    )


async def source_health(_request: Request) -> JSONResponse:
    return JSONResponse({"sources": SOURCE_REGISTRY.snapshot()})


async def procurement(request: Request) -> JSONResponse:
    days = max(1, min(int(request.query_params.get("days", "14")), 90))
    q = request.query_params.get("q", "")
    try:
        return JSONResponse(await _procurement(days=days, query=q))
    except Exception as exc:
        return JSONResponse({"error": type(exc).__name__, "message": str(exc)[:180]}, status_code=502)


async def overview(request: Request) -> JSONResponse:
    days = max(1, min(int(request.query_params.get("days", "14")), 90))
    procurement_result, ons_result, ukri_result = await asyncio.gather(
        _procurement(days=days),
        search_ons("business economy investment", limit=10),
        search_ukri("artificial intelligence automation", limit=10),
        return_exceptions=True,
    )
    for result in (ons_result, ukri_result):
        if isinstance(result, dict) and result.get("record_kind") == "factual-source-record":
            store().save_record(result)
    return JSONResponse(
        {
            "procurement": procurement_result if not isinstance(procurement_result, Exception) else {"error": str(procurement_result)[:180]},
            "macro": ons_result if not isinstance(ons_result, Exception) else {"error": str(ons_result)[:180]},
            "innovation": ukri_result if not isinstance(ukri_result, Exception) else {"error": str(ukri_result)[:180]},
            "source_health": SOURCE_REGISTRY.snapshot(),
            "ledger_count": len(store().ledger(limit=500)),
        }
    )


async def companies(request: Request) -> JSONResponse:
    q = request.query_params.get("q", "")
    try:
        result = await search_companies(q)
        for record in result.get("records", []):
            store().save_record(record)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"status": "FAILED", "error": str(exc)[:180], "records": []}, status_code=502)


async def macro(request: Request) -> JSONResponse:
    q = request.query_params.get("q", "business economy investment")
    try:
        record = await search_ons(q)
        store().save_record(record)
        return JSONResponse(record)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:180]}, status_code=502)


async def planning(_request: Request) -> JSONResponse:
    try:
        record = await fetch_planning()
        store().save_record(record)
        return JSONResponse(record)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:180]}, status_code=502)


async def environment(_request: Request) -> JSONResponse:
    try:
        record = await fetch_environment_agency()
        store().save_record(record)
        return JSONResponse(record)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:180]}, status_code=502)


async def ukri(request: Request) -> JSONResponse:
    q = request.query_params.get("q", "artificial intelligence automation")
    try:
        record = await search_ukri(q)
        store().save_record(record)
        return JSONResponse(record)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:180]}, status_code=502)


async def ledger(request: Request) -> JSONResponse:
    limit = max(1, min(int(request.query_params.get("limit", "100")), 500))
    return JSONResponse({"events": store().ledger(limit=limit)})


async def watchlist(request: Request) -> JSONResponse:
    if request.method == "GET":
        return JSONResponse({"items": store().watchlist()})
    body = await request.json()
    try:
        item = store().add_watch(
            str(body.get("entity_type") or ""),
            str(body.get("external_id") or ""),
            str(body.get("label") or ""),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(item, status_code=201)


routes = [
    Route("/commercial", home),
    Route("/commercial/", home),
    Route("/commercial/api/health", health),
    Route("/commercial/api/sources", source_health),
    Route("/commercial/api/overview", overview),
    Route("/commercial/api/procurement", procurement),
    Route("/commercial/api/companies", companies),
    Route("/commercial/api/macro", macro),
    Route("/commercial/api/planning", planning),
    Route("/commercial/api/environment", environment),
    Route("/commercial/api/ukri", ukri),
    Route("/commercial/api/ledger", ledger),
    Route("/commercial/api/watchlist", watchlist, methods=["GET", "POST"]),
]

app = Starlette(debug=False, routes=routes)


def run() -> None:
    import uvicorn

    host = os.getenv("COMMERCIAL_INTEL_HOST", "127.0.0.1")
    port = int(os.getenv("COMMERCIAL_INTEL_PORT", "8766"))
    uvicorn.run("world_intel_mcp.commercial_app:app", host=host, port=port, reload=False)


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Commercial Intelligence</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#070a0f;color:#e9eef5}body{margin:0}.wrap{max-width:1180px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:16px;align-items:end}.muted{color:#8b98a7}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:20px 0}.card{border:1px solid #202b38;background:#0d131b;border-radius:14px;padding:16px}.status{font-size:12px;padding:4px 8px;border-radius:99px;background:#13271d;color:#8de0aa}.bar{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}button,input{background:#101923;border:1px solid #2b3949;color:#eef;padding:9px 11px;border-radius:9px}button{cursor:pointer}.row{border-top:1px solid #1f2a36;padding:10px 0}.score{font-weight:700;color:#9fe0ba}pre{white-space:pre-wrap;word-break:break-word;max-height:440px;overflow:auto;font-size:12px}.danger{color:#ffb4a7}</style></head>
<body><div class="wrap"><div class="top"><div><h1>Personal Commercial & Capital Intelligence</h1><div class="muted">Source facts, provenance and deterministic signals. No trading or paid calls.</div></div><span class="status">LOCAL / PRIVATE</span></div>
<div class="bar"><button onclick="loadOverview()">Refresh overview</button><input id="q" placeholder="Search procurement"><button onclick="searchProc()">Search</button><input id="company" placeholder="Company name"><button onclick="searchCompany()">Companies House</button></div>
<div class="grid"><div class="card"><h3>Source health</h3><div id="sources">Loading…</div></div><div class="card"><h3>Top supplier momentum</h3><div id="suppliers">Loading…</div></div><div class="card"><h3>Post-award pressure</h3><div id="pressure">Loading…</div></div><div class="card"><h3>Ledger</h3><div id="ledger">Loading…</div></div></div>
<div class="card"><h3>Procurement</h3><div id="procurement">Loading…</div></div><div class="card" style="margin-top:14px"><h3>Raw result / provenance inspector</h3><pre id="raw"></pre></div></div>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
async function j(u,o){const r=await fetch(u,o);const d=await r.json();if(!r.ok)throw new Error(d.message||d.error||r.status);return d}
function rows(id,items,fn){document.getElementById(id).innerHTML=(items||[]).slice(0,20).map(fn).join('')||'<div class="muted">No observed records</div>'}
async function loadOverview(){try{const d=await j('/commercial/api/overview');const p=d.procurement||{};rows('procurement',p.notices,x=>`<div class="row"><b>${esc(x.title)}</b><div>${esc(x.buyer)} ${x.supplier?'→ '+esc(x.supplier):''}</div><div class="muted">${esc(x.source)} · ${esc(x.stage)} · ${esc(x.published||'')}</div></div>`);rows('suppliers',p.signals?.supplier_momentum,x=>`<div class="row"><span class="score">${esc(x.score)}</span> ${esc(x.supplier)}<div class="muted">${esc(x.explanation)}</div></div>`);rows('pressure',p.signals?.post_award_delivery_pressure,x=>`<div class="row"><span class="score">${esc(x.score)}</span> ${esc(x.supplier||x.buyer||x.notice_id)}<div class="muted">${esc(x.explanation)}</div></div>`);rows('sources',d.source_health,x=>`<div class="row"><b>${esc(x.source)}</b> — ${esc(x.status)}<div class="muted">last success: ${esc(x.last_success||'—')}</div></div>`);document.getElementById('ledger').textContent=`${d.ledger_count||0} stored observations`;document.getElementById('raw').textContent=JSON.stringify(d,null,2)}catch(e){document.getElementById('raw').textContent=e.message}}
async function searchProc(){const q=document.getElementById('q').value;const d=await j('/commercial/api/procurement?q='+encodeURIComponent(q));document.getElementById('raw').textContent=JSON.stringify(d,null,2);rows('procurement',d.notices,x=>`<div class="row"><b>${esc(x.title)}</b><div>${esc(x.buyer)}</div></div>`)}
async function searchCompany(){const q=document.getElementById('company').value;const d=await j('/commercial/api/companies?q='+encodeURIComponent(q));document.getElementById('raw').textContent=JSON.stringify(d,null,2)}
loadOverview();
</script></body></html>"""
