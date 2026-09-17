"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { token } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  PlatformBilling,
  signInvoice,
  type BillingOverview,
  type Invoice,
  type WalletProvider,
} from "../../../packages/platform-billing/src";
const billing = new PlatformBilling("/api", token);
const money = (micro: number) =>
  (micro / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 6 });
export function CryptoBilling({
  workspaceId,
  owner,
}: {
  workspaceId: string;
  owner: boolean;
}) {
  const [overview, setOverview] = useState<BillingOverview | null>(null);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [amount, setAmount] = useState(10_000_000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const refresh = useCallback(async () => {
    setOverview(await billing.overview(workspaceId));
  }, [workspaceId]);
  useEffect(() => {
    setOverview(null);
    setInvoice(null);
    setError("");
    refresh().catch((e) => setError(e.message));
  }, [refresh]);
  useEffect(() => {
    if (
      !invoice ||
      !["settlement_pending", "settling", "pending"].includes(invoice.status)
    )
      return;
    const timer = setInterval(() => {
      billing
        .invoice(invoice.id)
        .then(async (next) => {
          setInvoice(next);
          if (next.status === "paid") {
            setNotice("Payment confirmed. Your platform balance is ready.");
            await refresh();
          }
        })
        .catch((e) => setError(e.message));
    }, 4000);
    return () => clearInterval(timer);
  }, [invoice, refresh]);
  async function create() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setInvoice(
        await billing.createInvoice(workspaceId, amount, crypto.randomUUID()),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function pay() {
    if (!invoice || !overview) return;
    setBusy(true);
    setError("");
    setNotice("");
    let submitted = false;
    try {
      const wallet = (window as Window & { ethereum?: WalletProvider })
        .ethereum;
      if (!wallet)
        throw new Error(
          "Open Cubicle in a browser with an Ethereum-compatible wallet to pay.",
        );
      const signature = await signInvoice(
        wallet,
        invoice,
        overview,
        invoice.amount_micro_usdc,
      );
      // Once submitted, never ask for another signature automatically: settlement may be in flight.
      submitted = true;
      setInvoice({ ...invoice, status: "settlement_pending" });
      const result = await billing.pay(invoice.id, signature);
      setInvoice(result);
      if (result.status === "paid") {
        setNotice("Payment confirmed. Your platform balance is ready.");
        await refresh();
      }
    } catch (e) {
      const err = e as Error & { code?: number };
      setError(
        err.code === 4001
          ? "Wallet request cancelled. No payment was submitted."
          : submitted
            ? "Payment status needs checking. Do not pay again until this invoice is resolved."
            : err.message,
      );
    } finally {
      setBusy(false);
    }
  }
  const payable =
    invoice &&
    ["open", "created", "unpaid", "awaiting_payment"].includes(invoice.status);
  const pending =
    invoice &&
    ["settlement_pending", "settling", "pending"].includes(invoice.status);
  return (
    <section className="settings-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">PLATFORM BALANCE</span>
          <h1>A little room to grow.</h1>
          <p>Prepaid USDC credits for Cubicle and your platform services.</p>
        </div>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="setup-banner" role="status">
          {notice}
        </p>
      )}
      {!overview ? (
        <p className="muted">Loading payments…</p>
      ) : (
        <>
          {!overview.enabled && (
            <p className="setup-banner" role="status">
              {overview.reason ||
                "Crypto payments are not configured yet. No payment is required."}
            </p>
          )}
          {overview.test_network && (
            <p className="setup-banner">
              Test network · Test USDC only. These credits have no cash value.
            </p>
          )}
          <div className="billing-grid">
            <article className="settings-card">
              <span className="tiny-label">AVAILABLE CREDIT</span>
              <div className="billing-price">
                {money(overview.balance_micro_usdc)}
                <span> USDC</span>
              </div>
              <p>
                Your workspace balance is shared across supported services.
                Usage is charged at the rates below.
              </p>
              <h3>Service rates</h3>
              {overview.prices.map((price) => (
                <p key={price.service}>
                  {price.service === "agent-desktop" ||
                  price.service === "cubicle"
                    ? "Cubicle"
                    : price.service}
                  : {money(price.price_micro_usdc)} USDC / {price.unit}
                </p>
              ))}
              <Link className="text-link" href="/trial">
                Explore token-holder trials ↗
              </Link>
            </article>
            <article className="settings-card">
              <span className="tiny-label">ADD CREDIT</span>
              <h2>Pay from your wallet.</h2>
              <p>One-time payment. No subscription or automatic renewal.</p>
              {overview.network && (
                <p className="muted">
                  Network:{" "}
                  {overview.network === "eip155:84532"
                    ? "Base Sepolia (testnet)"
                    : overview.network === "eip155:8453"
                      ? "Base"
                      : overview.network === "eip155:31337"
                        ? "Local test network"
                        : overview.network}
                </p>
              )}
              <label htmlFor="topup-amount">Top-up amount</label>
              <select
                id="topup-amount"
                value={amount}
                disabled={busy || !!pending}
                onChange={(e) => setAmount(Number(e.target.value))}
              >
                <option value={10000000}>10 USDC</option>
                <option value={25000000}>25 USDC</option>
                <option value={50000000}>50 USDC</option>
              </select>
              <p className="muted">
                Your wallet authorizes the exact USDC amount. The payment
                facilitator submits the transaction and covers network gas; your
                wallet may show any additional costs before approval.
              </p>
              <Button
                onClick={create}
                disabled={!overview.enabled || !owner || busy || !!pending}
              >
                Create payment invoice
              </Button>
              {!owner && (
                <p className="muted">Only a workspace owner can add credit.</p>
              )}
            </article>
          </div>
          {invoice && (
            <article className="settings-card" aria-label="Payment invoice">
              <h2>{money(invoice.amount_micro_usdc)} USDC invoice</h2>
              <p role="status">
                {invoice.status === "paid"
                  ? "Paid"
                  : pending
                    ? "Checking settlement. Please keep this invoice for reference."
                    : invoice.status.replaceAll("_", " ")}
              </p>
              <p className="muted crypto-address">Invoice: {invoice.id}</p>
              <p className="muted crypto-address">
                Recipient: {invoice.recipient}
              </p>
              <p className="muted">
                Expires: {new Date(invoice.expires_at).toLocaleString()}
              </p>
              {payable && (
                <Button
                  disabled={busy || !owner || !overview.enabled}
                  onClick={pay}
                >
                  {busy ? "Waiting for wallet…" : "Authorize payment in wallet"}
                </Button>
              )}
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  billing
                    .invoice(invoice.id)
                    .then((next) => {
                      setInvoice(next);
                      return refresh();
                    })
                    .catch((e) => setError(e.message))
                }
              >
                Check payment status
              </Button>
            </article>
          )}
          <article className="settings-card" aria-label="Balance activity">
            <h2>Balance activity</h2>
            <p className="muted">
              Recent credits and service usage across this workspace.
            </p>
            {!overview.entries?.length ? (
              <p className="muted">No balance activity yet.</p>
            ) : (
              <ul className="invoice-history">
                {overview.entries.map((entry) => (
                  <li key={entry.id}>
                    <strong>
                      {entry.amount >= 0 ? "Credit" : "Debit"} ·{" "}
                      {entry.amount >= 0 ? "+" : "−"}
                      {money(Math.abs(entry.amount))} USDC
                    </strong>
                    <p>
                      {entry.service === "cubicle" ||
                      entry.service === "agent-desktop"
                        ? "Cubicle"
                        : entry.service || "Platform"}
                      {entry.amount < 0
                        ? ` · ${entry.units} ${entry.service === "cubicle" ? "minute(s)" : "unit(s)"} × ${money(entry.unit_price)} USDC`
                        : ""}
                    </p>
                    <p className="muted">
                      {entry.reason} ·{" "}
                      <time dateTime={entry.created_at}>
                        {new Date(entry.created_at).toLocaleString()}
                      </time>
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </article>
          <article className="settings-card">
            <h2>Payment history</h2>
            {overview.invoices.length === 0 ? (
              <p className="muted">No invoices yet.</p>
            ) : (
              <ul className="invoice-history">
                {overview.invoices.map((item) => (
                  <li key={item.id}>
                    <button
                      className="text-link"
                      onClick={() =>
                        billing
                          .invoice(item.id)
                          .then(setInvoice)
                          .catch((e) => setError(e.message))
                      }
                    >
                      {money(item.amount_micro_usdc)} USDC ·{" "}
                      {item.status.replaceAll("_", " ")}{" "}
                      <span className="crypto-address">{item.id}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </article>
        </>
      )}
    </section>
  );
}
