"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Setup = {
  development_mode: boolean;
  agent: { configured: boolean; model: string; action: string };
  authentication: { configured: boolean; action: string };
  billing: { configured: boolean; checkout_enabled: boolean; action: string };
  note: string;
};
export function ServiceSetup({ workspaceId }: { workspaceId: string }) {
  const [setup, setSetup] = useState<Setup | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api<Setup>(`/workspaces/${workspaceId}/setup`)
      .then((result) => {
        if (active) setSetup(result);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [workspaceId]);
  if (error) return <p role="alert">{error}</p>;
  if (!setup) return <p className="muted">Checking connected services…</p>;
  return (
    <section aria-label="Connected services">
      <h3>Connected services</h3>
      {(["agent", "authentication", "billing"] as const).map((key) => (
        <div key={key}>
          <h4>
            {key === "agent"
              ? "AI agent"
              : key === "authentication"
                ? "Sign-in"
                : "Billing"}
            : {setup[key].configured ? "Configured" : "Setup required"}
          </h4>
          {!setup[key].configured && (
            <p className="muted">{setup[key].action}</p>
          )}
        </div>
      ))}
      <p className="muted">{setup.note}</p>
    </section>
  );
}
