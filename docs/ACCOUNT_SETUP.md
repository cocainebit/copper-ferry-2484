# Accounts, AI provider, and billing setup

The app supports Supabase user sessions, email codes, Google/GitHub sign-in, workspace invitations, owner-managed Anthropic keys, and Stripe Checkout/Portal. Local development credentials are a convenience for one developer; disable both development flags before a public deployment.

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

## Stripe

Create two test-mode prices matching the published plans:

| Environment variable | Price |
| --- | --- |
| `STRIPE_SUBSCRIPTION_PRICE` | USD 29.00, recurring every month |
| `STRIPE_TOPUP_PRICE` | USD 10.00, one-time |

Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`. Configure the Billing Portal for cancellation and payment-method changes. Disable plan switching to unrelated products. Enable `LAUNCH_ENABLED` only after capacity and deployment checks pass.

Forward Stripe test webhooks to `/api/v1/billing/webhook` on the web origin (or `/v1/billing/webhook` directly on the API). Subscribe to:

- `invoice.paid`
- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Checkout requires an `Idempotency-Key` header and validates the configured price against the published amount/currency/recurrence. Webhooks use Stripe signature verification, customer binding, transactional grants, event deduplication, and invoice/session-level credit deduplication. Top-ups must match the configured price, quantity, amount, currency, and workspace metadata. Subscription status is fetched from Stripe to avoid stale cancellation events. A successful browser redirect never grants credits.

Test with Stripe test-mode credentials: initial subscription, renewal, failed payment, cancellation, duplicate/out-of-order webhooks, immediate top-up, and delayed-payment top-up. Check that each paid invoice grants 100 hours once and each top-up grants 50 hours once. Refunds/disputes still require an operational review and manual entitlement correction; automated refund policy is not implemented. No Stripe integration has been tested against a live account in this environment.

## Readiness

Owners can query `GET /v1/workspaces/{workspace_id}/setup` for configuration status. This reports presence, not external provider health. It contains no secret values. Public launch still requires actual end-to-end tests and production monitoring.

References: [Supabase local configuration](https://supabase.com/docs/guides/local-development/cli/config), [Supabase local email templates](https://supabase.com/docs/guides/local-development/customizing-email-templates).
