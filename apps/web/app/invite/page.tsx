"use client";
import { useState } from "react";
import Link from "next/link";
import { api, token, supabase } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Mark } from "@/components/brand";
export default function Invite() {
  const [message, setMessage] = useState(
    "Sign in with the invited email address, then join the workspace.",
  );
  return (
    <main className="auth-page">
      <div className="auth-card">
        <Mark size={38} />
        <h1>You’re invited.</h1>
        <p>{message}</p>
        <Button
          onClick={async () => {
            try {
              if (!(await token())) {
                sessionStorage.setItem(
                  "auth-return",
                  location.pathname + location.search,
                );
                location.href = "/login";
                return;
              }
              const t = new URLSearchParams(location.search).get("token");
              if (!t) throw new Error("Invitation token is missing");
              await api(`/invitations/${encodeURIComponent(t)}/accept`, "POST");
              sessionStorage.removeItem("auth-return");
              location.href = "/app";
            } catch (e) {
              setMessage((e as Error).message);
            }
          }}
        >
          Join workspace
        </Button>
        <Link
          className="text-link"
          href="/login"
          onClick={async (e) => {
            e.preventDefault();
            sessionStorage.removeItem("use-local-workspace");
            sessionStorage.setItem(
              "auth-return",
              location.pathname + location.search,
            );
            await supabase?.auth.signOut({ scope: "local" });
            location.href = "/login";
          }}
        >
          Sign in with another account
        </Link>
      </div>
    </main>
  );
}
