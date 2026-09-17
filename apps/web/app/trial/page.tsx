"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Copy,
  Gift,
  ShieldCheck,
  Wallet,
  Clock,
} from "lucide-react";
import { api, token, type Workspace } from "@/lib/api";
import { Mark } from "@/components/brand";
import { Button } from "@/components/ui/button";
export default function Trial() {
  const [config, setConfig] = useState<any>();
  const [workspace, setWorkspace] = useState("");
  const [wallet, setWallet] = useState("");
  const [intent, setIntent] = useState<any>();
  const [signature, setSignature] = useState("");
  const [payment, setPayment] = useState<any>();
  const [tx, setTx] = useState("");
  const [result, setResult] = useState<any>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    api("/config")
      .then(setConfig)
      .catch((e) => setError(e.message));
    (async () => {
      const signed = !!(await token());
      setSignedIn(signed);
      if (signed) {
        const w = await api<Workspace[]>("/workspaces");
        setWorkspace(w.find((x) => x.role === "owner")?.id || "");
      }
    })().catch((e) => setError(e.message));
  }, []);
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="trial-page">
      <nav className="landing-nav">
        <Link href="/" className="brand">
          <Mark />
          cubicle
        </Link>
        <Link className="text-link" href="/app">
          Workspace <ArrowRight size={15} />
        </Link>
      </nav>
      <div className="trial-layout">
        <section>
          <span className="eyebrow">
            <span className="pulse-dot" /> FOR PLATFORM TOKEN HOLDERS
          </span>
          <h1>
            Your tokens.
            <br />A week of possibilities.
          </h1>
          <p className="trial-intro">
            Try Cubicle for seven days.
            <br />A little proof of ownership. A whole computer to explore.
          </p>
          <div className="trial-steps">
            {[
              [
                Wallet,
                "Verify your wallet",
                "Sign a one-time message to prove the wallet belongs to you.",
              ],
              [
                ShieldCheck,
                "Confirm your eligibility",
                "Send exactly 1 platform token and retain at least 10,000 tokens.",
              ],
              [
                Clock,
                "Make the week yours",
                "Get seven days of access with 10 computer-hours. Bring your Anthropic API key.",
              ],
            ].map(([Icon, title, desc]) => {
              const I = Icon as typeof Wallet;
              return (
                <div key={String(title)}>
                  <I size={20} />
                  <div>
                    <h3>{String(title)}</h3>
                    <p>{String(desc)}</p>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="trial-fineprint">
            One trial per account and wallet for each service. No automatic
            subscription. The 1-token transfer is a payment, not a refundable
            deposit. You need at least 10,001 tokens before transferring,
            excluding network fees.
          </p>
        </section>
        <section className="trial-card">
          <Gift size={28} />
          <h2>
            {result
              ? "Your week starts now."
              : "A little proof. A fresh start."}
          </h2>
          {!config ? (
            <p>Loading eligibility…</p>
          ) : !config.trials_available ? (
            <>
              <p>Token-holder trials are coming soon.</p>
              <div className="notice">
                The platform token and network are not configured yet. Do not
                send tokens to any address for this trial.
              </div>
              <Link className="button primary" href="/app">
                Explore your workspace <ArrowRight size={16} />
              </Link>
            </>
          ) : !signedIn ? (
            <>
              <p>First, sign in to link your trial to your platform account.</p>
              <Link className="button primary" href="/login">
                Sign in to continue <ArrowRight size={16} />
              </Link>
            </>
          ) : !workspace ? (
            <>
              <p>Create a workspace before enrolling.</p>
              <Link className="button primary" href="/app">
                Create workspace
              </Link>
            </>
          ) : result ? (
            <>
              <div className="trial-success">
                <Check size={30} />
              </div>
              <p>
                Access ends {new Date(result.expires_at + "Z").toLocaleString()}
                .
              </p>
              <Link className="button primary" href="/app">
                Open your computer <ArrowRight size={16} />
              </Link>
            </>
          ) : !intent ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () =>
                  setIntent(
                    await api("/trials/intents", "POST", {
                      workspace_id: workspace,
                      service: "agent-desktop",
                      wallet,
                    }),
                  ),
                );
              }}
            >
              <label>
                Your wallet address
                <input
                  value={wallet}
                  onChange={(e) => setWallet(e.target.value)}
                  required
                  placeholder="Wallet address"
                />
              </label>
              <Button disabled={busy}>
                Verify ownership <ArrowRight size={16} />
              </Button>
            </form>
          ) : !payment ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () =>
                  setPayment(
                    await api(
                      `/trials/intents/${intent.id}/verify-wallet`,
                      "POST",
                      { signature },
                    ),
                  ),
                );
              }}
            >
              <p>
                Sign this exact message with your wallet’s message-signing tool.
                Signing does not transfer tokens.
              </p>
              <pre className="signature-message">{intent.message}</pre>
              <button
                type="button"
                className="text-link"
                onClick={() => navigator.clipboard.writeText(intent.message)}
              >
                <Copy size={14} />
                Copy message
              </button>
              <label>
                Wallet signature
                <textarea
                  required
                  value={signature}
                  onChange={(e) => setSignature(e.target.value)}
                  placeholder="Paste signed message signature"
                />
              </label>
              <Button disabled={busy}>Confirm signature</Button>
            </form>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () =>
                  setResult(
                    await api(`/trials/intents/${intent.id}/redeem`, "POST", {
                      transaction_id: tx,
                    }),
                  ),
                );
              }}
            >
              <div className="payment-details">
                <p>
                  Network <strong>{payment.chain}</strong>
                </p>
                <p>
                  Token <code>{payment.token}</code>
                </p>
                <p>
                  Amount <strong>Exactly 1 token</strong>
                </p>
                <p>
                  Recipient <code>{payment.recipient}</code>
                </p>
              </div>
              <p>
                Transfer directly from your verified wallet before{" "}
                {new Date(payment.expires_at + "Z").toLocaleTimeString()}. Keep
                at least 10,000 tokens after payment.
              </p>
              <label>
                Transaction ID
                <input
                  value={tx}
                  onChange={(e) => setTx(e.target.value)}
                  required
                />
              </label>
              <Button disabled={busy}>
                {busy
                  ? "Verifying on-chain…"
                  : "Verify payment and start trial"}
              </Button>
            </form>
          )}
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
        </section>
      </div>
    </main>
  );
}
