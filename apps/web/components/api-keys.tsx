"use client";
import { useEffect, useState } from "react";
import { KeyRound, Copy, Check, X } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Key = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};

const SCOPES: [string, string][] = [
  ["read", "Read computers, files, events and tasks"],
  ["control", "Screenshot, mouse, keyboard, shell and files"],
  ["manage", "Create, start, stop, rename, configure and delete"],
];

export function ApiKeys({ workspaceId }: { workspaceId: string }) {
  const [keys, setKeys] = useState<Key[]>([]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read", "control"]);
  const [expires, setExpires] = useState(0);
  const [created, setCreated] = useState<{ key: string; name: string } | null>(
    null,
  );
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load() {
    setKeys(await api<Key[]>(`/workspaces/${workspaceId}/api-keys`));
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
  const live = keys.filter((k) => !k.revoked_at);
  return (
    <article className="settings-card">
      <div className="card-title">
        <KeyRound size={20} />
        <div>
          <h2>API keys</h2>
          <p>
            Let agents, the CLI, SDKs and the MCP server drive this
            workspace&apos;s computers without a browser session.
          </p>
        </div>
        <span className="tag">{live.length} ACTIVE</span>
      </div>
      {created && (
        <div className="key-reveal" role="status">
          <strong>Copy this key now. It will not be shown again.</strong>
          <div>
            <code>{created.key}</code>
            <button
              aria-label="Copy API key"
              onClick={async () => {
                await navigator.clipboard.writeText(created.key);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
            <button aria-label="Dismiss" onClick={() => setCreated(null)}>
              <X size={14} />
            </button>
          </div>
          <p className="field-note">
            Use it as <code>Authorization: Bearer &lt;key&gt;</code> or set{" "}
            <code>CUBICLE_API_KEY</code> for the CLI and MCP server.
          </p>
        </div>
      )}
      <form
        className="key-form"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            const result = await api<Key & { key: string }>(
              `/workspaces/${workspaceId}/api-keys`,
              "POST",
              {
                name,
                scopes,
                ...(expires ? { expires_in_days: expires } : {}),
              },
            );
            setCreated({ key: result.key, name: result.name });
            setName("");
          });
        }}
      >
        <div className="inline-form">
          <input
            aria-label="Key name"
            placeholder="What will use this key? e.g. research agent"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={80}
          />
          <select
            aria-label="Key expiry"
            value={expires}
            onChange={(e) => setExpires(Number(e.target.value))}
          >
            <option value={0}>Never expires</option>
            <option value={7}>Expires in 7 days</option>
            <option value={30}>Expires in 30 days</option>
            <option value={90}>Expires in 90 days</option>
          </select>
          <Button disabled={busy || !name.trim() || !scopes.length}>
            Create key
          </Button>
        </div>
        <div className="scope-list">
          {SCOPES.map(([scope, help]) => (
            <label key={scope}>
              <input
                type="checkbox"
                checked={scopes.includes(scope)}
                disabled={scope === "read"}
                onChange={(e) =>
                  setScopes((old) =>
                    e.target.checked
                      ? [...old, scope]
                      : old.filter((s) => s !== scope),
                  )
                }
              />
              <span>
                <strong>{scope}</strong> {help}
              </span>
            </label>
          ))}
        </div>
      </form>
      {message && (
        <p role="alert" className="field-note">
          {message}
        </p>
      )}
      {live.length === 0 ? (
        <p className="field-note">No active keys.</p>
      ) : (
        live.map((k) => (
          <div className="member-row" key={k.id}>
            <code>{k.prefix}_…</code>
            <span>{k.name}</span>
            <span className="tag">{k.scopes.join(" · ")}</span>
            <small>
              {k.last_used_at
                ? `used ${new Date(k.last_used_at + "Z").toLocaleString()}`
                : "never used"}
              {k.expires_at
                ? ` · expires ${new Date(k.expires_at + "Z").toLocaleDateString()}`
                : ""}
            </small>
            <button
              aria-label={`Revoke ${k.name}`}
              title="Revoke"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api(`/api-keys/${k.id}`, "DELETE");
                })
              }
            >
              <X size={15} />
            </button>
          </div>
        ))
      )}
      <p className="field-note">
        Keys act as you inside this workspace only. They can never create other
        keys, change the Anthropic credential, invite members or touch billing.
        See the developer guide for the REST routes, SDKs, CLI and MCP server.
      </p>
    </article>
  );
}
