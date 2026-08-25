# Direct standalone launch

This branch is explicitly independent of DAWN runtime.

## Runtime
- Use the repository's existing Starlette dashboard and collector.
- Launch with `./run-dashboard.sh` on the always-on host.
- Expose privately through the already-existing Tailscale Serve route if remote access is required.
- Do not use a public tunnel or paid hosting merely to satisfy launch.

## Acceptance
- Dashboard process is running on the host.
- Existing world-intel sources continue collecting through the shared Fetcher/Cache/CircuitBreaker stack.
- `/commercial` must be added/verified before this branch is promoted as the personal commercial-intelligence app.
- P0 UK sources should degrade independently rather than blocking the dashboard.

## Cost and safety
GBP0 incremental. No trading, outreach, credential widening, public posting, or dependency on DAWN orchestration.
