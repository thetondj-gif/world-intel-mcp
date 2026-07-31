# DAWN Commercial Signal Intelligence — Capability Foundry Wave 1

## Status

`CAPABILITY_RESEARCH_COMPLETE`

This branch does not start the collector, dashboard, Qdrant integration or any persistent listener.

## Objective

Create a restricted commercial-intelligence profile that turns selected public signals into evidence-backed reasons to prioritise an account, prepare a meeting or draft an outreach angle.

## Initial operation allowlist

- company enrichment;
- material company events;
- executive changes;
- earnings and financial pressure;
- cyber incidents;
- relevant government contracts;
- supply-chain and infrastructure events;
- news convergence.

## First implementation slice

1. Map the approved upstream tools to DAWN's commercial-signal schema.
2. Exclude military, surveillance, financial-trading and unrelated world-intelligence operations from the default profile.
3. Add source timestamps, freshness, confidence and provenance requirements.
4. Add bounded HTTP, caching and response-size controls.
5. Create synthetic and recorded-response tests with no live collector requirement.
6. Produce a standard-envelope adapter and sample account-signal evidence package.

## Intended output

```text
account
→ verified public signals
→ relevance and freshness scoring
→ customer-problem hypothesis
→ evidence-linked outreach angle
→ meeting brief
```

## Wave 1 boundary

No financial trading, persistent collection daemon, public dashboard, unrestricted MCP exposure, outbound communication, production database mutation or live DAWN connection is permitted.

## Connection gate

The capability becomes connection-ready only after the restricted tool profile, schema mapping, evidence policy, tests, security review and rollback instructions are complete.
