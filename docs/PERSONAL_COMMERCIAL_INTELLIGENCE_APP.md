# Personal Commercial & Capital Intelligence App

## Status

BUILDING — local/private-use web app, independent of DAWN runtime.

## Goal

Turn the existing World Intelligence MCP collector plus the already-implemented UK official-data adapters into one personal web application for commercial opportunity discovery, procurement intelligence, company enrichment and capital-research signals.

The application must keep source facts separate from derived/inferred intelligence and retain provenance for every externally sourced fact.

## Existing assets to reuse

### world-intel-mcp
- Existing Fetcher, Cache, CircuitBreaker and Qdrant VectorStore.
- Existing collector daemon and dashboard infrastructure.
- Existing 100+ intelligence tools/sources for markets, macro, news, social, SEC, GitHub, technology, infrastructure, shipping, cyber and other contextual signals.
- Existing Starlette dashboard; no new frontend build system is required for MVP.

### Existing UK official-data implementation in hermes-agent
Read before reimplementation:
- `integrations/dawn-sdr/intelligence/OFFICIAL_ADAPTERS.md`
- `integrations/dawn-sdr/intelligence/adapters.py`
- `integrations/dawn-sdr/intelligence/adapter-status.json`
- `integrations/dawn-sector-intelligence/official_api_enrichment.py`
- `integrations/dawn-sector-intelligence/authoritative-source-registry.json`

Known existing official routes include Companies House, Contracts Finder OCDS, Find a Tender OCDS, ONS, Planning Data, Environment Agency, YouTube Data API, Food Standards Agency FHRS, DfE Explore Education Statistics, UKRI Gateway to Research and NCBI/PubMed. Charity Commission has a known credential but its dedicated adapter may still need completing. HM Land Registry Price Paid and Gazette are registered future adapters.

### Financial side tooling
`thetondj-gif/cfo-stack` is an accounting/finance-ops toolkit, not the application base. Do not couple the intelligence application to its ledger engine. Reuse concepts or exported personal financial data only through explicit adapters later.

## MVP views

1. **Overview**
   - source health summary
   - significant new procurement awards/opportunities
   - supplier momentum
   - contract expiry/renewal candidates
   - high-scoring post-award commercial prospects
   - notable capital/market signals

2. **Procurement**
   - Find a Tender notices
   - Contracts Finder notices
   - award / opportunity split
   - buyer, supplier, value, dates, OCID / stable IDs
   - filters by date, stage, sector and organisation

3. **Companies**
   - Companies House identity anchor (`company_number`)
   - status, SIC, incorporation, filing/company profile facts available through configured routes
   - linked awards and buyers
   - public payments when adapter is available
   - news/market/technology context where relevant

4. **Capital Research**
   - public procurement-derived company events
   - world-intel market/macro/news context
   - SEC/market data for listed US entities where available
   - event ledger and watchlist
   - paper/research signals only; no live trading or financial execution

5. **Source Health**
   - source
   - configured / credential present (boolean only; never reveal secret)
   - last attempt
   - last success
   - status: LIVE / DEGRADED / MISSING_CREDENTIAL / RATE_LIMITED / FAILED / STALE / NOT_IMPLEMENTED
   - latest error summary
   - freshness / cache age

## Source priority

### P0 — wire and prove first
- Companies House
- Contracts Finder OCDS
- Find a Tender OCDS
- ONS
- Planning Data
- Environment Agency
- UKRI Gateway to Research
- FSA FHRS
- existing world-intel market/macro/news/social/GitHub sources

### P1
- Charity Commission dedicated adapter
- DfE Explore Education Statistics
- YouTube Data API
- NCBI/PubMed
- HM Land Registry Price Paid
- The Gazette linked data / statutory notices
- public-contract payment transparency route if not already represented by FTS records

### P2 optional enrichment
- other existing world-intel sources where a concrete company/sector/geographic relationship exists

## Data model

### Raw observation
- source_id
- stable_source_id / OCID / company_number where applicable
- retrieved_at
- source_url
- payload_hash
- raw_payload or durable raw reference
- licence / permitted-use metadata where known

### Entity
- canonical entity id
- entity type (company, buyer, supplier, contract, director/person, sector, geography, ticker)
- canonical external IDs
- aliases

### Event
- event id
- event type
- observed / published / effective timestamps
- linked entities
- factual attributes
- provenance refs

### Derived signal
- signal id
- signal type
- score (0-100 where applicable)
- explanation
- evidence refs
- model/rule version
- generated_at
- `is_inference=true`

## Initial proprietary scores

- Supplier Momentum Score
- Post-Award Delivery Pressure Score
- Public Sector Dependency Score
- Buyer Demand Momentum Score
- Contract Renewal / Rebid Probability
- Automation Opportunity Score
- Capital Research Signal Score

Scores must be deterministic/rule-based in MVP where practical. LLM output may explain or summarise evidence but must not silently alter source facts.

## Architecture

```text
existing public/free APIs + configured keyed APIs
        -> shared Fetcher / Cache / CircuitBreaker
        -> raw observations + provenance
        -> entity resolution
        -> SQLite/Postgres-ready intelligence store
        -> optional Qdrant semantic history
        -> deterministic scoring
        -> Starlette JSON endpoints + personal dashboard
        -> optional OpenAI explanation/synthesis layer
```

MVP may use SQLite for relational persistence if it keeps the schema migration-ready. Qdrant remains optional and must degrade cleanly.

## OpenAI usage

OpenAI is optional enhancement, not collection infrastructure.

Allowed initial use:
- explain why a signal is interesting
- summarise linked evidence
- produce a concise company/contract research brief

Requirements:
- server-side `OPENAI_API_KEY` only
- no key in browser/source control
- graceful disabled state when key absent
- evidence IDs supplied to prompts and returned alongside explanation
- no autonomous trading, outreach or external commitment

## Security / cost

- Local/private-use by default.
- GBP0 incremental target: use existing free/public sources and current keys/quotas.
- Never log secret values.
- Do not commit `.env`.
- Bounded calls, caching, rate-limit awareness and circuit breaking required.
- Missing keyed source is a visible status, not an application failure.

## Acceptance for first build

A local user can launch the existing dashboard package and reach a `/commercial` experience that:

1. shows a source-health matrix;
2. performs bounded live or cached collection from available P0 UK sources;
3. stores provenance-bearing observations;
4. displays procurement notices and resolved companies where possible;
5. enriches the view with existing world-intel context;
6. computes at least Supplier Momentum and Post-Award Delivery Pressure using transparent rules;
7. exposes a watchlist/event ledger data contract;
8. cleanly reports sources blocked by a missing key, rate limit, endpoint/contract change or incomplete adapter;
9. has tests for parsers/source clients/scoring and no secret-bearing fixtures;
10. makes no trade, outreach, public publish or paid call.

## Build principle

Do not wait for every source to be perfect. Implement adapters behind a shared registry, make each source independently observable, and let the useful subset operate while blocked sources report their exact state.
