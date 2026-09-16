"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Github, Mail } from "lucide-react";
import { supabase } from "@/lib/api";
import { Mark } from "@/components/brand";
import { Button } from "@/components/ui/button";
export default function Login() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  function destination() {
    const path = sessionStorage.getItem("auth-return") || "/app";
    return path.startsWith("/invite?token=") ? path : "/app";
  }
  async function oauth(provider: "google" | "github") {
    sessionStorage.removeItem("use-local-workspace");
    if (!supabase) {
      setError("Sign-in is not configured yet.");
      return;
    }
    setError("");
    setBusy(true);
    const { error } = await supabase.auth.signInWithOAuth({
      provider,
      options: { redirectTo: location.origin + destination() },
    });
    if (error) setError(error.message);
    setBusy(false);
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    sessionStorage.removeItem("use-local-workspace");
    setError("");
    setBusy(true);
    try {
      if (!supabase) throw new Error("Email sign-in is not configured yet.");
      if (sent) {
        const { error } = await supabase.auth.verifyOtp({
          email,
          token: code,
          type: "email",
        });
        if (error) throw error;
        location.href = destination();
      } else {
        const { error } = await supabase.auth.signInWithOtp({
          email,
          options: { emailRedirectTo: location.origin + destination() },
        });
        if (error) throw error;
        setSent(true);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <Link href="/" className="back-link">
        <ArrowLeft size={16} /> Back to home
      </Link>
      <div className="auth-card">
        <Mark size={38} />
        <h1>
          Your next idea
          <br />
          starts here.
        </h1>
        <p className="muted">Sign in or create your workspace.</p>
        <Button variant="ghost" disabled={busy} onClick={() => oauth("google")}>
          <span className="google-g">G</span>Continue with Google
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => oauth("github")}>
          <Github size={18} />
          Continue with GitHub
        </Button>
        <div className="divider">
          <span>or use your email</span>
        </div>
        <form onSubmit={submit}>
          <label>
            Email address
            <input
              type="email"
              required
              disabled={sent || busy}
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          {sent && (
            <label>
              Verification code
              <input
                required
                autoComplete="one-time-code"
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
          )}
          <Button disabled={busy}>
            {busy
              ? "One moment…"
              : sent
                ? "Verify and continue"
                : "Continue with email"}
            <ArrowRight size={16} />
          </Button>
        </form>
        {sent && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setSent(false);
              setCode("");
              setError("");
            }}
          >
            Use another email or resend code
          </Button>
        )}
        {error && (
          <p role="alert" className="error-text">
            {error}
          </p>
        )}
        {sent && (
          <p className="muted">Check your email for a sign-in link or code.</p>
        )}
        {process.env.NEXT_PUBLIC_DEV_MODE === "true" && (
          <Link
            className="text-link"
            href="/app"
            onClick={() =>
              sessionStorage.setItem("use-local-workspace", "true")
            }
          >
            Open local development workspace <ArrowRight size={14} />
          </Link>
        )}
        <p className="auth-footnote">Your desktop, your files, your control.</p>
      </div>
    </main>
  );
}
