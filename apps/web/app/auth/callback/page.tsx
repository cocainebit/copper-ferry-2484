"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Mark } from "@/components/brand";
import { completeSignIn } from "@/lib/platform-auth";
function destination() {
  try {
    const path = sessionStorage.getItem("auth-return") || "/app";
    return path.startsWith("/invite?token=") ? path : "/app";
  } catch {
    return "/app";
  }
}
export default function AuthCallback() {
  const [error, setError] = useState("");
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    completeSignIn(new URLSearchParams(window.location.search))
      .then(() => {
        try {
          sessionStorage.removeItem("auth-return");
        } catch {
          // Nothing to clean up if storage is unavailable.
        }
        location.replace(destination());
      })
      .catch((e) => setError((e as Error).message));
  }, []);
  return (
    <main className="auth-page">
      <div className="auth-card">
        <Mark size={38} />
        <h1>{error ? "Sign-in did not finish." : "Signing you in…"}</h1>
        <p className="muted">
          {error
            ? "Nothing was changed. You can try again."
            : "One moment while we finish with the Instance platform."}
        </p>
        {error && (
          <p role="alert" className="error-text">
            {error}
          </p>
        )}
        {error && (
          <Link className="text-link" href="/login">
            Back to sign in <ArrowRight size={14} />
          </Link>
        )}
      </div>
    </main>
  );
}
