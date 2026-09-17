"use client";
import { useCallback, useEffect, useState } from "react";
import { Play, Trash2, Copy, Check } from "lucide-react";
import { api, type Computer } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Automation = {
  id: string;
  name: string;
  enabled: boolean;
  trigger: {
    kind: string;
    cron?: string;
    timezone?: string;
    every_minutes?: number;
    path?: string;
    process?: string;
  };
  action: { kind: string; command?: string; prompt?: string };
  start_if_stopped: boolean;
  timeout_minutes: number;
  next_fire_at: string | null;
  last_fired_at: string | null;
  webhook_path: string | null;
};
type Execution = {
  id: string;
  reason: string;
  status: string;
  output: string;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

const when = (value: string | null) =>
  value ? new Date(value + "Z").toLocaleString() : "never";

function describeTrigger(t: Automation["trigger"]) {
  switch (t.kind) {
    case "schedule":
      return `cron ${t.cron} (${t.timezone || "UTC"})`;
    case "interval":
      return `every ${t.every_minutes} minutes`;
    case "webhook":
      return "webhook call";
    case "file":
      return `~/${t.path} changes`;
    case "process":
      return `${t.process} stops`;
    default:
      return t.kind;
  }
}

function describeAction(a: Automation["action"]) {
  if (a.kind === "command") return `run: ${a.command}`;
  if (a.kind === "agent_task") return `agent: ${a.prompt}`;
  return a.kind === "start" ? "start the computer" : "stop the computer";
}

export function AutomationsPanel({
  computer,
  owner,
}: {
  computer: Computer;
  owner: boolean;
}) {
  const [items, setItems] = useState<Automation[]>([]);
  const [runs, setRuns] = useState<Record<string, Execution[]>>({});
  const [open, setOpen] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [token, setToken] = useState<{ path: string; token: string } | null>(
    null,
  );
  const [copied, setCopied] = useState(false);
  const [name, setName] = useState("Nightly report");
  const [triggerKind, setTriggerKind] = useState("schedule");
  const [cron, setCron] = useState("0 9 * * mon-fri");
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const [every, setEvery] = useState(60);
  const [path, setPath] = useState("Downloads/report.csv");
  const [processName, setProcessName] = useState("chromium");
  const [actionKind, setActionKind] = useState("command");
  const [command, setCommand] = useState("date >> ~/automation.log");
  const [prompt, setPrompt] = useState("");
  const [startIfStopped, setStartIfStopped] = useState(false);
  const [timeout, setTimeoutMinutes] = useState(30);

  const load = useCallback(async () => {
    setItems(await api<Automation[]>(`/computers/${computer.id}/automations`));
  }, [computer.id]);
  const loadRuns = useCallback(async (id: string) => {
    const result = await api<Execution[]>(`/automations/${id}/runs`);
    setRuns((old) => ({ ...old, [id]: result }));
  }, []);
  useEffect(() => {
    load().catch((e) => setMessage(e.message));
    const timer = setInterval(() => {
      load().catch(() => {});
      if (open) loadRuns(open).catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [load, loadRuns, open]);

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

  const trigger =
    triggerKind === "schedule"
      ? { kind: "schedule", cron, timezone }
      : triggerKind === "interval"
        ? { kind: "interval", every_minutes: every }
        : triggerKind === "file"
          ? { kind: "file", path }
          : triggerKind === "process"
            ? { kind: "process", process: processName }
            : { kind: "webhook" };
  const action =
    actionKind === "command"
      ? { kind: "command", command }
      : actionKind === "agent_task"
        ? { kind: "agent_task", prompt }
        : { kind: actionKind };
  const watcher = triggerKind === "file" || triggerKind === "process";

  return (
    <div className="automations-panel">
      {token && (
        <div className="key-reveal" role="status">
          <strong>Webhook token, shown once</strong>
          <div>
            <code>
              curl -X POST -H &quot;X-Cubicle-Token: {token.token}&quot;{" "}
              {location.origin}/api{token.path}
            </code>
            <button
              aria-label="Copy webhook command"
              onClick={async () => {
                await navigator.clipboard.writeText(
                  `curl -X POST -H "X-Cubicle-Token: ${token.token}" ${location.origin}/api${token.path}`,
                );
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </div>
        </div>
      )}
      {items.length === 0 && (
        <p className="field-note">
          No automations yet. Schedules, webhooks and watchers run commands or
          agent tasks on this computer while you are away.
        </p>
      )}
      {items.map((a) => (
        <article
          key={a.id}
          className={"automation " + (a.enabled ? "" : "off")}
        >
          <div className="app-card-head">
            <strong>{a.name}</strong>
            <span className="tag">{a.enabled ? "ENABLED" : "PAUSED"}</span>
          </div>
          <p>
            When {describeTrigger(a.trigger)}, {describeAction(a.action)}
            {a.start_if_stopped ? " (starts the computer if needed)" : ""}.
          </p>
          <p className="field-note">
            {a.trigger.kind === "schedule" || a.trigger.kind === "interval"
              ? `Next ${when(a.next_fire_at)} · `
              : ""}
            last fired {when(a.last_fired_at)}
          </p>
          <div className="app-card-actions">
            <Button
              variant="ghost"
              disabled={!owner || busy}
              onClick={() =>
                run(async () => {
                  await api(`/automations/${a.id}/run`, "POST");
                  setOpen(a.id);
                  await loadRuns(a.id);
                })
              }
            >
              <Play size={13} /> Run now
            </Button>
            <button
              className="text-link"
              disabled={!owner || busy}
              onClick={() =>
                run(async () => {
                  await api(`/automations/${a.id}`, "PATCH", {
                    enabled: !a.enabled,
                  });
                })
              }
            >
              {a.enabled ? "Pause" : "Resume"}
            </button>
            <button
              className="text-link"
              onClick={() => {
                const next = open === a.id ? "" : a.id;
                setOpen(next);
                if (next) loadRuns(next).catch(() => {});
              }}
            >
              {open === a.id ? "Hide history" : "History"}
            </button>
            <button
              className="text-link"
              aria-label={`Delete ${a.name}`}
              disabled={!owner || busy}
              onClick={() =>
                run(async () => {
                  await api(`/automations/${a.id}`, "DELETE");
                })
              }
            >
              <Trash2 size={12} /> Delete
            </button>
          </div>
          {open === a.id && (
            <div className="automation-runs">
              {(runs[a.id] || []).length === 0 && (
                <p className="field-note">No executions yet.</p>
              )}
              {(runs[a.id] || []).map((r) => (
                <details key={r.id}>
                  <summary>
                    <span className={"run-dot " + r.status} />
                    {r.status} · {r.reason} · {when(r.created_at)}
                    {r.error ? ` · ${r.error}` : ""}
                  </summary>
                  {r.output && <pre className="app-log">{r.output}</pre>}
                </details>
              ))}
            </div>
          )}
        </article>
      ))}
      {owner && (
        <form
          className="automation-form"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              const created = await api<
                Automation & { webhook_token?: string }
              >(`/computers/${computer.id}/automations`, "POST", {
                name,
                trigger,
                action,
                start_if_stopped: !watcher && startIfStopped,
                timeout_minutes: timeout,
              });
              setToken(
                created.webhook_token && created.webhook_path
                  ? { path: created.webhook_path, token: created.webhook_token }
                  : null,
              );
            });
          }}
        >
          <h3 className="registry-heading">New automation</h3>
          <label>
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={80}
            />
          </label>
          <div className="automation-row">
            <label>
              When
              <select
                aria-label="Trigger"
                value={triggerKind}
                onChange={(e) => setTriggerKind(e.target.value)}
              >
                <option value="schedule">On a schedule (cron)</option>
                <option value="interval">Every N minutes</option>
                <option value="webhook">A webhook is called</option>
                <option value="file">A file in Home changes</option>
                <option value="process">A process stops</option>
              </select>
            </label>
            {triggerKind === "schedule" && (
              <>
                <label>
                  Cron
                  <input
                    aria-label="Cron expression"
                    value={cron}
                    onChange={(e) => setCron(e.target.value)}
                  />
                </label>
                <label>
                  Time zone
                  <input
                    aria-label="Time zone"
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                  />
                </label>
              </>
            )}
            {triggerKind === "interval" && (
              <label>
                Minutes
                <input
                  type="number"
                  min={5}
                  max={10080}
                  value={every}
                  onChange={(e) => setEvery(Number(e.target.value))}
                />
              </label>
            )}
            {triggerKind === "file" && (
              <label>
                Path under Home
                <input value={path} onChange={(e) => setPath(e.target.value)} />
              </label>
            )}
            {triggerKind === "process" && (
              <label>
                Process name
                <input
                  value={processName}
                  onChange={(e) => setProcessName(e.target.value)}
                />
              </label>
            )}
          </div>
          <div className="automation-row">
            <label>
              Do
              <select
                aria-label="Action"
                value={actionKind}
                onChange={(e) => setActionKind(e.target.value)}
              >
                <option value="command">Run a command</option>
                <option value="agent_task">Give the agent a task</option>
                {!watcher && <option value="start">Start the computer</option>}
                <option value="stop">Stop the computer</option>
              </select>
            </label>
            <label>
              Timeout (minutes)
              <input
                type="number"
                min={1}
                max={240}
                value={timeout}
                onChange={(e) => setTimeoutMinutes(Number(e.target.value))}
              />
            </label>
          </div>
          {actionKind === "command" && (
            <label>
              Command (runs as administrator, workspace secrets available)
              <textarea
                rows={2}
                value={command}
                onChange={(e) => setCommand(e.target.value)}
              />
            </label>
          )}
          {actionKind === "agent_task" && (
            <label>
              Task for the agent
              <textarea
                rows={3}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Check the dashboard and save a summary to ~/reports"
              />
            </label>
          )}
          {!watcher &&
            (actionKind === "command" || actionKind === "agent_task") && (
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={startIfStopped}
                  onChange={(e) => setStartIfStopped(e.target.checked)}
                />
                Start the computer if it is stopped (runtime charges apply)
              </label>
            )}
          <Button disabled={busy}>Create automation</Button>
          {message && (
            <p role="alert" className="field-note error-text">
              {message}
            </p>
          )}
          <p className="field-note">
            Schedules run at most every 5 minutes and never backfill missed
            slots. File and process watchers check every 30 seconds while the
            computer runs.
          </p>
        </form>
      )}
    </div>
  );
}
