"use client";
import { useCallback, useEffect, useState } from "react";
import { Download, Play, Trash2, RefreshCw, Lock, Loader2 } from "lucide-react";
import { api, type Computer } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Install = {
  id: string;
  status: string;
  error: string | null;
  log: string;
  updated_at: string;
};
type App = {
  id: string;
  name: string;
  category: string;
  description: string;
  launchable: boolean;
  removable: boolean;
  requires: string[];
  install: Install | null;
};
type SecretInfo = {
  names: string[];
  injected_at: string | null;
};

export function AppsPanel({
  computer,
  owner,
}: {
  computer: Computer;
  owner: boolean;
}) {
  const [apps, setApps] = useState<App[]>([]);
  const [secrets, setSecrets] = useState<SecretInfo | null>(null);
  const [open, setOpen] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const running = computer.status === "running";
  const controlling = computer.controller !== "agent";
  const load = useCallback(async () => {
    const [a, s] = await Promise.all([
      api<App[]>(`/computers/${computer.id}/apps`),
      api<SecretInfo>(`/computers/${computer.id}/secrets`),
    ]);
    setApps(a);
    setSecrets(s);
  }, [computer.id]);
  useEffect(() => {
    load().catch((e) => setMessage(e.message));
    const timer = setInterval(() => load().catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [load]);
  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setMessage("");
    try {
      await fn();
      await load();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  const byId = Object.fromEntries(apps.map((a) => [a.id, a]));
  const categories = Array.from(new Set(apps.map((a) => a.category)));
  return (
    <div className="apps-panel">
      <div className="apps-toolbar">
        <span>
          <Lock size={13} />
          {secrets
            ? `${secrets.names.length} secret${secrets.names.length === 1 ? "" : "s"} available to shells and the agent` +
              (secrets.injected_at
                ? ` · injected ${new Date(secrets.injected_at + "Z").toLocaleTimeString()}`
                : " · injected at next start")
            : "Secrets…"}
        </span>
        <div>
          <button
            disabled={!running || !owner || busy !== ""}
            title="Re-inject workspace secrets now"
            onClick={() =>
              act("secrets", () =>
                api(`/computers/${computer.id}/secrets/refresh`, "POST"),
              )
            }
          >
            <RefreshCw size={13} /> Refresh secrets
          </button>
          <button
            disabled={!running || !controlling || busy !== ""}
            title="Verify installed apps against the live system"
            onClick={() =>
              act("check", () =>
                api(`/computers/${computer.id}/apps/check`, "POST"),
              )
            }
          >
            <RefreshCw size={13} /> Check apps
          </button>
        </div>
      </div>
      {message && (
        <p role="alert" className="field-note">
          {message}
        </p>
      )}
      {!running && (
        <p className="field-note">
          Start the computer to install or launch apps. Installed apps persist
          in the saved system.
        </p>
      )}
      {categories.map((category) => (
        <section key={category} className="apps-category">
          <h3>{category}</h3>
          <div className="apps-grid">
            {apps
              .filter((a) => a.category === category)
              .map((a) => {
                const status = a.install?.status;
                const changing =
                  status === "installing" || status === "removing";
                const missingRequirement = a.requires.find(
                  (r) => byId[r]?.install?.status !== "installed",
                );
                return (
                  <article
                    key={a.id}
                    className={"app-card " + (status || "absent")}
                  >
                    <div className="app-card-head">
                      <strong>{a.name}</strong>
                      <span className="tag">
                        {changing ? (
                          <>
                            <Loader2 className="spin" size={10} /> {status}
                          </>
                        ) : (
                          status || "not installed"
                        )}
                      </span>
                    </div>
                    <p>{a.description}</p>
                    {missingRequirement && status !== "installed" && (
                      <p className="field-note">
                        Needs {byId[missingRequirement]?.name} first.
                      </p>
                    )}
                    {a.install?.error && (
                      <p className="field-note error-text">{a.install.error}</p>
                    )}
                    <div className="app-card-actions">
                      {status !== "installed" && (
                        <Button
                          variant="ghost"
                          disabled={
                            !running ||
                            !owner ||
                            changing ||
                            !!missingRequirement ||
                            busy !== ""
                          }
                          onClick={() =>
                            act(a.id, () =>
                              api(
                                `/computers/${computer.id}/apps/${a.id}/install`,
                                "POST",
                              ),
                            )
                          }
                        >
                          <Download size={13} />{" "}
                          {status === "failed" ? "Retry install" : "Install"}
                        </Button>
                      )}
                      {status === "installed" && a.launchable && (
                        <Button
                          variant="ghost"
                          disabled={!running || !controlling || busy !== ""}
                          title={
                            controlling
                              ? "Open on the desktop"
                              : "Take control to launch apps"
                          }
                          onClick={() =>
                            act(a.id, () =>
                              api(
                                `/computers/${computer.id}/apps/${a.id}/launch`,
                                "POST",
                              ),
                            )
                          }
                        >
                          <Play size={13} /> Launch
                        </Button>
                      )}
                      {status === "installed" && a.removable && (
                        <button
                          className="text-link"
                          disabled={!running || !owner || busy !== ""}
                          onClick={() =>
                            act(a.id, () =>
                              api(
                                `/computers/${computer.id}/apps/${a.id}/remove`,
                                "POST",
                              ),
                            )
                          }
                        >
                          <Trash2 size={12} /> Remove
                        </button>
                      )}
                      {a.install?.log && (
                        <button
                          className="text-link"
                          onClick={() => setOpen(open === a.id ? "" : a.id)}
                        >
                          {open === a.id ? "Hide log" : "Log"}
                        </button>
                      )}
                    </div>
                    {open === a.id && a.install?.log && (
                      <pre className="app-log">{a.install.log}</pre>
                    )}
                  </article>
                );
              })}
          </div>
        </section>
      ))}
    </div>
  );
}
