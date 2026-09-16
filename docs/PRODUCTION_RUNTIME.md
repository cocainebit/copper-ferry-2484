# Production runtime scaffold

This is a **reviewable deployment scaffold**, not an already deployed or security-certified service. It never changes the existing macOS development desktop. It requires a dedicated Linux host, Docker's iptables firewall backend, gVisor `runsc`, and operator review of the host's routing and firewall. It is not suitable for Docker Desktop, a shared personal server, or Docker's native nftables backend without adaptation.

## Topology

Only Caddy publishes public ports (80/443). The Next.js frontend, FastAPI API, worker, and OpenSandbox manager communicate on a separate control network. The API/worker use an external production Postgres URL and share stable encryption/signing keys. The frontend is built with Supabase publishable configuration and development auth disabled.

OpenSandbox alone holds the Docker socket; that service is trusted host administration software. Its API has a required strong key, no published port, and a separate dedicated sandbox network. Tenant desktops have no Docker socket, host bind mounts, CDP, VNC or execd routes exposed by the application. The viewer connects through the API's authenticated websocket gateway. OpenSandbox does dynamically publish host ports internally; the host firewall is therefore **mandatory** to prevent direct public access to them.

OpenSandbox's production config requires `secure_runtime.type=gvisor` and `docker_runtime=runsc`. The pinned upstream source checks the Docker runtime registry at startup and raises when a configured runtime is unavailable (`server/opensandbox_server/services/runtime_resolver.py`). It also passes the runtime through to sandbox creation. This does not install gVisor and does not replace a real desktop compatibility/isolation test.

## Configuration and build

Use a protected deployment environment or secret store. Required variables: `APP_DOMAIN`, `DATABASE_URL` (production Postgres), `SUPABASE_URL`, `SUPABASE_ANON_KEY` (publishable), `ENCRYPTION_KEY`, `SIGNING_KEY`, `OPS_TOKEN`, `OPENSANDBOX_API_KEY`, `DESKTOP_IMAGE`. Stripe/trial settings are optional and remain disabled without configuration. This scaffold hardcodes `LAUNCH_ENABLED=false`; changing it belongs to the reviewed launch step.

Do not run `docker compose config` without `--quiet` around real secrets. It expands environment values. Validate without printing them:

```sh
docker compose -f compose.production.yaml config --quiet
```

The production Dockerfiles copy only explicit source/dependency files; developer `.env` files and virtual environments are not baked into images. Build the desktop image from `infra/desktop` and set `DESKTOP_IMAGE` to the reviewed tag/digest. Build service images with `docker compose -f compose.production.yaml build`. Pin deployed image digests after compatibility testing; the checked-in tag-based image references are development scaffolding, not a locked production supply chain.

## Dedicated Linux host preparation

1. Install/configure gVisor `runsc` as a Docker OCI runtime using your host vendor's supported procedure. Never remove the secure-runtime configuration merely to get the production stack to start.
2. Ensure `172.30.0.0/24` does not overlap host/VPN/cloud routes. This scaffold reserves manager address `172.30.0.2`; if changing it, update Compose and firewall together.
3. Create the **dedicated** external network, without attaching unrelated containers:

   ```sh
   docker network create --driver bridge --subnet 172.30.0.0/24 \
     --opt com.docker.network.bridge.name=br-ad-sbx \
     --opt com.docker.network.bridge.enable_icc=false agent-desktop-sandboxes
   ```

4. Enable `br_netfilter` and `net.bridge.bridge-nf-call-iptables=1`, `net.bridge.bridge-nf-call-ip6tables=1` persistently using your host's normal administration procedure. Install `iptables`, `ip6tables`, Python 3 and ripgrep. The script checks these prerequisites; it does not silently change global sysctls.
5. Review [firewall.sh](../infra/production/firewall.sh), including existing firewall ordering. On this dedicated host only, explicitly apply it with `sudo bash infra/production/firewall.sh --apply`. It adds scoped chains and jumps, never flushes unrelated rules, blocks sandbox-to-host/private/metadata/neighbor traffic and external direct ingress, and blocks sandbox IPv6 entirely. Public internet access is allowed. The trusted OpenSandbox manager has an explicit network exception.
6. Integrate reapplication and `--check` into the host's boot/service order **before starting Docker application workloads**. The marker file is merely an installation interlock, not proof that rules survived reboot. The included `infra/production/agent-desktop.service` example reapplies and checks rules before starting Compose in the foreground. Review its paths and install it explicitly; store production environment variables in a root-readable `/etc/agent-desktop/production.env`. Compose container auto-restart is disabled so Docker reboot cannot start desktops before this preflight. Existing dynamically created sandbox containers also require host restart-policy inspection; stop all desktops before a planned reboot. Never rely on the marker alone. No systemd unit is installed automatically.
7. Run `sudo env PRODUCTION_ISOLATION_ACK=reviewed bash infra/production/check-host.sh`. Apply database migrations with the maintenance service before running API/worker.
8. Start the stack only after configuration, migration and host checks pass. Confirm `/health/ready` and the private bearer-protected `/internal/metrics` endpoint, then boot a test desktop and verify websocket viewing, Chromium under gVisor, agent tasks and restart persistence.

No firewall command or production stack was applied to the developer machine. `--check` only checks expected rules exist; operators must also audit rule ordering, existing ACCEPT rules and host cloud firewall behavior. Reapply before accepting traffic following network/firewall/Docker changes. The host public firewall should allow only HTTPS/HTTP and explicitly controlled administration sources.

## Required isolation acceptance tests

From an actual untrusted desktop, prove rejection of host gateway/public-host management ports, cloud metadata addresses, RFC1918 destinations, adjacent tenant VNC/execd/CDP, and IPv6 bypass. From an external host, prove ports 40000–40199 and all backend ports are inaccessible. Verify trusted proxy viewing, public HTTPS egress and DNS work. These tests must run against the chosen Linux host; local macOS success is insufficient. Custom routing, DNS proxies, VPNs and already established conntrack flows can change results. Start with no running tenants when applying initial firewall policy.

## Storage and remaining launch gates

Ordinary Docker named volumes **do not enforce the advertised 20 GB per-desktop quota**. The application persists home data in named volumes and snapshot images in the Docker image store. Neither is bounded by this Compose file. Before public launch choose and integrate a storage backend with independently enforced per-tenant quotas (for example an operator-managed project-quota filesystem or CSI storage with actual quota enforcement), enforce snapshot/clone storage limits, and test full-disk behavior. A CPU/RAM limit or Docker writable-layer size setting does not quota mounted home volumes. This remains a launch blocker.

Backups must include production Postgres, OpenSandbox manager metadata, desktop home volumes, snapshot images and stable encryption keys, with off-host encryption and tested restore. A backup that omits home volumes or custom snapshot images cannot restore a desktop. See the repository backup tooling and roadblocks for current implementation status.

This scaffold is a single-host starting point. Host failover, multi-host scheduling, managed TLS/private network policy, rate limits/abuse detection, full observability and verified recovery objectives require deployment-specific work. Do not present gVisor and firewall scaffolding as a completed production security review.
