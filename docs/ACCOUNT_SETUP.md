# Accounts, AI provider, and billing setup

Cubicle supports Supabase user sessions, email codes, Google/GitHub sign-in, workspace invitations, owner-managed Anthropic keys, and prepaid USDC payments through x402. Local development credentials are a convenience for one developer; disable both development flags before a public deployment.

## Local authentication without a cloud account

A local Supabase configuration is provided in `supabase/config.toml`. It uses ports 55320–55326 to avoid the app's Postgres port. The isolated stack has been booted using Supabase CLI 2.117.0. Local email-code delivery, session verification through our backend JWKS checks, refresh, and logout all passed a real smoke test.

From the repository root (npx installs the pinned CLI if needed):

```sh
services/api/.venv/bin/python scripts/local-auth-key.py
npx --yes supabase@2.117.0 start --exclude studio,realtime,storage-api,imgproxy,postgres-meta,edge-runtime,logflare,vector,supavisor
npx --yes supabase@2.117.0 status
```

The generated ES256 signing key is private, permission 0600, git-ignored, and never printed. Never copy a local key into production. The backend intentionally does not accept legacy HS256 tokens. Local Supabase versions must support `auth.signing_keys_path`; verify user tokens against `http://127.0.0.1:55321/auth/v1/.well-known/jwks.json` before considering authentication ready.

Set backend `SUPABASE_URL=http://127.0.0.1:55321`. Set frontend `NEXT_PUBLIC_SUPABASE_URL` to the same URL and `NEXT_PUBLIC_SUPABASE_ANON_KEY` to the publishable/anon key shown by `supabase status`. Never put the service-role or secret key in frontend variables. Restart both servers. Inspect local test mail at `http://localhost:55324`. The API's existing application Postgres database can remain separate from Supabase Auth.

Run the credential-free local integration check with:

```sh
services/api/.venv/bin/python scripts/smoke-local-auth.py
# Also verify the running API accepts sessions and denies cross-workspace access:
services/api/.venv/bin/python scripts/smoke-local-auth.py --application-api http://127.0.0.1:8000
```

It sends only to the local test inbox, creates an isolated `example.test` user, and never prints keys, email codes, or JWTs. It leaves the test user and test message for inspection. `supabase status` itself prints local secrets; do not paste its raw output into logs or tickets.

Google/GitHub OAuth require their own registered applications even locally. Email-code authentication can be tested with the local mail inbox without those accounts. Hosted email should use an authenticated SMTP provider and the included eight-digit email template. Local SMTP settings and templates are not automatically deployed to a hosted project.

## Hosted sign-in and shared platform accounts

Use one Supabase project for the main platform and the desktop subwebsite. Configure each app with the same public Supabase URL/key and configure the backend issuer to match. Each origin has its own browser session; sharing a project shares identity but does not automatically create cross-subdomain single sign-on.

In Supabase, enable Google and GitHub providers, register their Supabase callback URL with each provider, configure a verified mail sender, and use asymmetric ES256/RS256 signing keys. Allow-list exact deployed application redirect URLs, including invitation return paths. Keep wildcard redirects limited to local development.

The backend verifies token signature, issuer, audience, expiry, issued-at, subject, and authenticated role. Anonymous and service-role sessions are rejected. Invitations require the invited email and expire after seven days. The invitation page retains its return path during sign-in; switching accounts signs out the current browser session.

Verification checklist:

1. Sign up with an email code, then sign out and sign in again.
2. Verify Google and GitHub redirects using real provider test accounts.
3. Invite a second account and confirm it has member access but cannot edit billing or provider keys.
4. Confirm a wrong-email invitation and expired JWT are rejected.
5. Set `DEV_MODE=false` and `NEXT_PUBLIC_DEV_MODE=false` in deployment; verify the local development token fails.

## Anthropic BYOK

An owner adds a key under Settings. The API checks it against Anthropic's models endpoint before saving encrypted credentials. Keys never appear in readiness output; the worker decrypts them only server-side. An accepted key does not prove sufficient provider credits, model access, or successful computer use. Test a harmless real task on a running desktop, pause it, take control, resume, and test an approval before marking the agent integration verified.

## Crypto billing and shared service accounts

The selected payment flow is prepaid USDC through x402. Stripe account setup is not required for this flow. Its older backend integration remains for compatibility; Cubicle's billing UI now uses crypto invoices and the shared workspace balance.

Payments are disabled by default. The default development network is Base Sepolia with test USDC. Configure and validate the rail using [crypto operations](CRYPTO_OPERATIONS.md); do not ask customers to send funds until a real test transaction and reconciliation exercise pass. The actual production treasury, network, pricing and refund procedures remain deployment inputs.

Workspace owners create and authorize invoices. Members can inspect balance and payment history. Wallet signing does not replace Supabase authentication, and a payment wallet does not automatically become an account owner. The supported wallet flow uses EOA EIP-3009 signatures and the server's `extra.invoiceNonce`; use the [shared billing client](../packages/platform-billing/README.md) for other first-party websites.

The main platform and Cubicle can share identity and the same workspace balance. Additional services register a price and a separate backend credential, then debit usage through the private central API. Never expose service credentials in browser code. See [payment integration](CRYPTO_PAYMENTS.md) for the routes and account boundaries.

Token-holder trials remain a separate service-specific entitlement. Their original `agent-desktop` service ID is retained for compatibility, and their token adapter still needs the real platform token/network configuration.

## Readiness

Owners can query `GET /v1/workspaces/{workspace_id}/setup` for configuration status. This reports presence, not external provider health. It contains no secret values. Public launch still requires actual end-to-end tests and production monitoring.

References: [Supabase local configuration](https://supabase.com/docs/guides/local-development/cli/config), [Supabase local email templates](https://supabase.com/docs/guides/local-development/customizing-email-templates).

## Signing in through Instance (platform identity)

Cubicle accepts access tokens issued by the Instance platform alongside its own Supabase sessions, so the two work at once while accounts move across.

Configure the API (`services/api/.env`):

```dotenv
PLATFORM_URL=http://127.0.0.1:8760
PLATFORM_SERVICE_TOKEN=<from: cd ~/platform && pnpm admin service create cubicle cubicle>
PLATFORM_ISSUER=http://127.0.0.1:8760/api/auth
PLATFORM_AUDIENCE=http://127.0.0.1:8000
```

and the dashboard (`apps/web/.env.local`):

```dotenv
NEXT_PUBLIC_PLATFORM_URL=http://127.0.0.1:8760
NEXT_PUBLIC_PLATFORM_CLIENT_ID=<from: pnpm admin client create Cubicle http://127.0.0.1:3000/auth/callback http://127.0.0.1:8000>
```

The platform must run with `OAUTH_RESOURCES=<Cubicle API URL>` so its tokens carry that audience. Verification checks issuer, audience, expiry and signature against the platform's JWKS (`{issuer}/jwks`); better-auth signs with Ed25519, and ES256 and RS256 are accepted for the other key types it can be configured with. Tokens that are not platform tokens fall through to Supabase, so nothing breaks mid-migration.

The browser uses the authorization code flow with PKCE (S256) as a public client: no client secret ever reaches the dashboard. Tokens are kept per browser and refreshed with the refresh token.

### What linking does to existing data

The first time a platform account signs in, Cubicle adopts the matching legacy identity and rewrites every stored user id (workspace membership, API key owners, trial entitlements and intents, automations, secrets and passes) in one transaction, then records the link so it happens once.

It finds the legacy identity by verified email, and failing that by a linked wallet address, because a wallet sign-in creates an account with no email at all. It never merges two different legacy users into one account: when the keys disagree, or either matches more than one legacy user, the sign-in is treated as a new member and the data is left alone.

Workspaces are mapped to the payer's platform organization (matched by its `personal-<user id>` slug), which is what charges are recorded against. Two workspaces may share one organization; the only effect is that their charges appear together in that person's payment history.
