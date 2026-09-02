# AGENTS.md — World Intel MCP

Before substantive estate work, read Google Drive `CURRENT_CANONICAL_ARCHITECTURE` (file ID `1na1pKjIho0lSwb5mkcIygfVNiGDAam-tEYowVnFgzUw`). This takes precedence over older estate guidance where there is any conflict. Search newest approved canon and recent verified commits before older documents.

## Estate role
Shared grounded intelligence/search capability. It may supply raw observations or retrieval to Signal Foundry, CCI and other consumers, but it does not own canonical downstream product conclusions.

## Rules
- Preserve source URL/identifier, observed time and provenance.
- Do not create a parallel canonical signal/opportunity store when Signal Foundry/shared contracts already own that layer.
- Its SQLite cache and private Qdrant store are operational/derived and rebuildable, not the sole durable home of reusable business intelligence.
- Any material, reusable signal discovered here must be promotable into the shared intelligence fabric with a stable ID/fingerprint, provenance, timestamp, source type and downstream linkage. Durable output must not die inside the World Intel cache/vector store.
- Social/buyer pain, commercial opportunity, tender/sector intelligence and finance-relevant observations should feed the existing shared Signals/CCI contracts rather than spawn new stores.
- MCP is an integration surface, not an architectural requirement for every consumer.
- Health/availability must be real, not inferred from configuration alone.
- Composition does not mean source merger.
- Do not create a new Markdown file when an existing canonical/read-first file should be updated.

## Output quality
A successful fetch or MCP response is an observation, not a verified business conclusion. Preserve uncertainty and provenance. Any customer-facing product built from this capability must meet the current production-readiness gate in `CURRENT_CANONICAL_ARCHITECTURE`: build/integration/E2E, failure paths, security/data boundaries where relevant, performance/stress appropriate to expected use, recovery/rollback and live canary before it is called production-ready.
