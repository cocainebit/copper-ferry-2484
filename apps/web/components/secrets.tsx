"use client";
import { useEffect, useState } from "react";
import { Lock, X } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Secret = {
  id: string;
  name: string;
  created_by: string;
  updated_at: string;
};

export function Secrets({ workspaceId }: { workspaceId: string }) {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load() {
    setSecrets(await api<Secret[]>(`/workspaces/${workspaceId}/secrets`));
  }
  useEffect(() => {
    load().catch((e) => setMessage(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
      await load();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const valid = /^[A-Z][A-Z0-9_]{0,63}$/.test(name);
  return (
    <article className="settings-card">
      <div className="card-title">
        <Lock size={20} />
        <div>
          <h2>Secrets</h2>
          <p>
            Encrypted values your computers receive at boot as environment
            variables. Never stored in system snapshots or shown again.
          </p>
        </div>
        <span className="tag">{secrets.length} STORED</span>
      </div>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await api(`/workspaces/${workspaceId}/secrets/${name}`, "PUT", {
              value,
            });
            setName("");
            setValue("");
          });
        }}
      >
        <input
          aria-label="Secret name"
          placeholder="OPENAI_API_KEY"
          value={name}
          onChange={(e) => setName(e.target.value.toUpperCase())}
          required
          maxLength={64}
          style={{ maxWidth: 220 }}
        />
        <input
          aria-label="Secret value"
          type="password"
          autoComplete="off"
          placeholder="value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required
          maxLength={8192}
        />
        <Button disabled={busy || !valid || !value}>
          {secrets.some((s) => s.name === name) ? "Replace" : "Save"}
        </Button>
      </form>
      {name && !valid && (
        <p className="field-note">
          Names are UPPER_SNAKE_CASE and cannot shadow system variables.
        </p>
      )}
      {message && (
        <p role="alert" className="field-note">
          {message}
        </p>
      )}
      {secrets.length === 0 ? (
        <p className="field-note">No secrets yet.</p>
      ) : (
        secrets.map((s) => (
          <div className="member-row" key={s.id}>
            <code>{s.name}</code>
            <small>
              updated {new Date(s.updated_at + "Z").toLocaleString()}
            </small>
            <button
              aria-label={`Delete ${s.name}`}
              title="Delete"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api(
                    `/workspaces/${workspaceId}/secrets/${s.name}`,
                    "DELETE",
                  );
                })
              }
            >
              <X size={15} />
            </button>
          </div>
        ))
      )}
      <p className="field-note">
        Available to login shells: the dashboard terminal, the computer
        API&apos;s bash route and the built-in agent&apos;s bash tool. Apps
        launched from the desktop menu do not see them. Running computers pick
        up changes on their next start or when you refresh secrets from the
        computer&apos;s Apps tab.
      </p>
    </article>
  );
}
