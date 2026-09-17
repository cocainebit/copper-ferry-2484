"use client";
import { useCallback, useEffect, useState } from "react";
import { Layers, Loader2, RotateCcw, Hammer } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Version = {
  id: string;
  name: string;
  definition_id: string;
  version: number;
  digest: string;
  status: string;
  requires_secrets: string[];
  created_at: string;
};
type Definition = { id: string; name: string; versions: Version[] };
type Starter = { id: string; name: string; spec: any; digest: string };
type Detail = Version & {
  spec: any;
  build_log: string;
  missing_secrets: string[];
};

const EXAMPLE = JSON.stringify(
  {
    description: "What this environment is for",
    apps: ["firefox", "git-tools"],
    packages: ["jq"],
    files: [{ path: "/etc/motd", content: "Built by Cubicle\n" }],
    run: ["echo ready > /opt/cubicle/ready"],
    startup: [],
    env: { EDITOR: "nano" },
    requires_secrets: [],
    cpu: 2,
    memory_gib: 4,
    storage_gib: 20,
    resolution: "1440x900",
    idle_timeout_minutes: 15,
  },
  null,
  2,
);

export function TemplateRegistry({ workspaceId }: { workspaceId: string }) {
  const [starters, setStarters] = useState<Starter[]>([]);
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [name, setName] = useState("");
  const [spec, setSpec] = useState(EXAMPLE);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    const [s, d] = await Promise.all([
      api<Starter[]>("/template-starters"),
      api<Definition[]>(`/workspaces/${workspaceId}/template-definitions`),
    ]);
    setStarters(s);
    setDefinitions(d);
  }, [workspaceId]);
  useEffect(() => {
    load().catch((e) => setMessage(e.message));
    const timer = setInterval(() => load().catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [load]);
  useEffect(() => {
    if (!detail || detail.status !== "building") return;
    const timer = setInterval(
      () =>
        api<Detail>(`/templates/${detail.id}`)
          .then(setDetail)
          .catch(() => {}),
      4000,
    );
    return () => clearInterval(timer);
  }, [detail]);
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
  async function publish(definitionName: string, body: unknown) {
    const result = await api<{ template: Version; built: boolean }>(
      `/workspaces/${workspaceId}/template-definitions`,
      "POST",
      { name: definitionName, spec: body },
    );
    setMessage(
      result.built
        ? `Building ${result.template.name} v${result.template.version}. Computers can use it once it is ready.`
        : `${result.template.name} v${result.template.version} already has this exact spec; nothing to rebuild.`,
    );
    setDetail(await api<Detail>(`/templates/${result.template.id}`));
  }
  return (
    <article className="settings-card">
      <div className="card-title">
        <Layers size={20} />
        <div>
          <h2>Template registry</h2>
          <p>
            Declarative, versioned environments. Each published spec builds once
            into a template you can create computers from; changing the spec
            makes a new version.
          </p>
        </div>
        <span className="tag">{definitions.length} DEFINITIONS</span>
      </div>
      <h3 className="registry-heading">Starters</h3>
      <div className="apps-grid">
        {starters.map((s) => (
          <article className="app-card" key={s.id}>
            <div className="app-card-head">
              <strong>{s.name}</strong>
            </div>
            <p>{s.spec.description}</p>
            <p className="field-note">
              {[...s.spec.apps, ...s.spec.packages].join(", ")}
              {s.spec.requires_secrets.length
                ? ` · needs ${s.spec.requires_secrets.join(", ")}`
                : ""}
            </p>
            <div className="app-card-actions">
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => run(() => publish(s.name, s.spec))}
              >
                <Hammer size={13} /> Build
              </Button>
              <button
                className="text-link"
                onClick={() => {
                  setName(s.name);
                  setSpec(JSON.stringify(s.spec, null, 2));
                }}
              >
                Customize
              </button>
            </div>
          </article>
        ))}
      </div>
      <h3 className="registry-heading">Your definitions</h3>
      {definitions.length === 0 && (
        <p className="field-note">No definitions yet.</p>
      )}
      {definitions.map((d) => (
        <div className="registry-definition" key={d.id}>
          <strong>{d.name}</strong>
          <div>
            {d.versions.map((v) => (
              <button
                key={v.id}
                className={
                  "registry-version " +
                  v.status +
                  (detail?.id === v.id ? " selected" : "")
                }
                onClick={() =>
                  run(async () =>
                    setDetail(await api<Detail>(`/templates/${v.id}`)),
                  )
                }
              >
                v{v.version}{" "}
                {v.status === "building" ? (
                  <Loader2 className="spin" size={10} />
                ) : (
                  v.status
                )}
              </button>
            ))}
          </div>
        </div>
      ))}
      {detail && (
        <div className="registry-detail">
          <div className="app-card-head">
            <strong>
              {detail.name} v{detail.version}
            </strong>
            <span className="tag">{detail.status}</span>
          </div>
          <p className="field-note">
            {detail.digest}
            {detail.missing_secrets?.length
              ? ` · add workspace secrets before use: ${detail.missing_secrets.join(", ")}`
              : ""}
          </p>
          <div className="app-card-actions">
            <button
              className="text-link"
              onClick={() => {
                setName(detail.name);
                setSpec(JSON.stringify(detail.spec, null, 2));
              }}
            >
              Edit as new version
            </button>
            {detail.status === "failed" && (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await api(`/templates/${detail.id}/rebuild`, "POST");
                    setDetail(await api<Detail>(`/templates/${detail.id}`));
                  })
                }
              >
                <RotateCcw size={13} /> Retry build
              </Button>
            )}
          </div>
          <pre className="app-log">
            {detail.build_log ||
              (detail.status === "building"
                ? "Building… the log appears when the build finishes."
                : "No build output recorded.")}
          </pre>
        </div>
      )}
      <h3 className="registry-heading">Publish a spec</h3>
      <form
        className="registry-form"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            let body;
            try {
              body = JSON.parse(spec);
            } catch {
              throw new Error("The spec is not valid JSON");
            }
            await publish(name, body);
          });
        }}
      >
        <input
          aria-label="Definition name"
          placeholder="Definition name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={80}
        />
        <textarea
          aria-label="Template spec JSON"
          value={spec}
          onChange={(e) => setSpec(e.target.value)}
          rows={14}
          spellCheck={false}
        />
        <Button disabled={busy || !name.trim()}>
          <Hammer size={14} /> Publish and build
        </Button>
      </form>
      {message && (
        <p role="status" className="field-note">
          {message}
        </p>
      )}
      <p className="field-note">
        Specs hold apps from the catalog, Debian packages, system files, root
        build steps, desktop startup commands, non-secret environment variables
        and the names of workspace secrets a computer needs. Never put secret
        values in a spec: they would be baked into the snapshot.
      </p>
    </article>
  );
}
