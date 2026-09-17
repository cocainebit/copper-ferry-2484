"use client";

import { useEffect, useState } from "react";
import { api, type Computer } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Template = { id: string; name: string; status: string };
type Job = { id: string; kind: string; status: string; error?: string };

export function PlatformFeatures({
  workspaceId,
  computers,
  onRefresh,
}: {
  workspaceId: string;
  computers: Computer[];
  onRefresh?: () => void;
}) {
  const [selected, setSelected] = useState("");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [name, setName] = useState("");
  const [cpu, setCpu] = useState(2);
  const [memory, setMemory] = useState(4);
  const [storage, setStorage] = useState(20);
  const [quotaEnforced, setQuotaEnforced] = useState(false);
  const [resolution, setResolution] = useState("1440x900");
  const [idleTimeout, setIdleTimeout] = useState(15);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const stopped = computers.filter((c) => c.status === "stopped");
  const cid = stopped.some((c) => c.id === selected)
    ? selected
    : stopped[0]?.id || "";
  async function refresh() {
    const [t, j] = await Promise.all([
      api<Template[]>(`/workspaces/${workspaceId}/templates`),
      api<Job[]>(`/workspaces/${workspaceId}/feature-jobs`),
    ]);
    setTemplates(t);
    setJobs(j);
  }
  useEffect(() => {
    let alive = true;
    const load = () =>
      Promise.all([
        api<Template[]>(`/workspaces/${workspaceId}/templates`),
        api<Job[]>(`/workspaces/${workspaceId}/feature-jobs`),
      ])
        .then(([t, j]) => {
          if (alive) {
            setTemplates(t);
            setJobs(j);
          }
        })
        .catch((e) => {
          if (alive) setMessage(e.message);
        });
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [workspaceId]);
  useEffect(() => {
    let alive = true;
    if (cid)
      api<{
        cpu: number;
        memory_gib: number;
        storage_gib: number;
        storage_quota_enforced: boolean;
        resolution: string;
        idle_timeout_minutes: number;
      }>(`/computers/${cid}/profile`)
        .then((p) => {
          if (alive) {
            setCpu(p.cpu);
            setMemory(p.memory_gib);
            setStorage(p.storage_gib || 20);
            setQuotaEnforced(!!p.storage_quota_enforced);
            setResolution(p.resolution || "1440x900");
            setIdleTimeout(p.idle_timeout_minutes ?? 15);
          }
        })
        .catch((e) => {
          if (alive) setMessage(e.message);
        });
    return () => {
      alive = false;
    };
  }, [cid]);
  async function act(path: string, method: string, body?: unknown) {
    setBusy(true);
    setMessage("");
    try {
      await api(path, method, body);
      await refresh();
      onRefresh?.();
      setMessage(
        method === "PUT"
          ? "Resources saved for the next start."
          : "Request queued. You can follow its progress below.",
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      aria-labelledby="desktop-customization"
      style={{ display: "grid", gap: 20, maxWidth: 760 }}
    >
      <div>
        <h2 id="desktop-customization">Desktop customization</h2>
        <p>
          Stop a computer to change its resources, clone it, or save a template.
        </p>
      </div>
      <label>
        Stopped computer{" "}
        <select
          aria-label="Stopped computer"
          value={cid}
          onChange={(e) => setSelected(e.target.value)}
        >
          {!stopped.length && <option value="">No stopped computers</option>}
          {stopped.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <div
        style={{
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
          alignItems: "end",
        }}
      >
        <label>
          CPU{" "}
          <select
            aria-label="CPU"
            value={cpu}
            onChange={(e) => setCpu(Number(e.target.value))}
          >
            <option value={1}>1 core</option>
            <option value={2}>2 cores</option>
          </select>
        </label>
        <label>
          Memory{" "}
          <select
            aria-label="Memory"
            value={memory}
            onChange={(e) => setMemory(Number(e.target.value))}
          >
            <option value={2}>2 GiB</option>
            <option value={4}>4 GiB</option>
          </select>
        </label>
        <label>
          Storage{" "}
          <select
            aria-label="Storage"
            value={storage}
            disabled={busy || !cid}
            onChange={(e) => setStorage(Number(e.target.value))}
          >
            <option value={20}>20 GiB</option>
            <option value={50}>50 GiB</option>
            <option value={100}>100 GiB</option>
          </select>
        </label>
        <label>
          Display resolution{" "}
          <select
            aria-label="Display resolution"
            value={resolution}
            disabled={busy || !cid}
            onChange={(e) => setResolution(e.target.value)}
          >
            <option value="1280x720">1280 × 720</option>
            <option value="1440x900">1440 × 900</option>
            <option value="1920x1080">1920 × 1080</option>
          </select>
        </label>
        <label>
          Idle stop{" "}
          <select
            aria-label="Idle stop"
            value={idleTimeout}
            disabled={busy || !cid}
            onChange={(e) => setIdleTimeout(Number(e.target.value))}
          >
            <option value={5}>After 5 minutes</option>
            <option value={15}>After 15 minutes</option>
            <option value={30}>After 30 minutes</option>
            <option value={60}>After 1 hour</option>
            <option value={0}>Always on</option>
            {![0, 5, 15, 30, 60].includes(idleTimeout) && (
              <option value={idleTimeout}>After {idleTimeout} minutes</option>
            )}
          </select>
        </label>
        <Button
          disabled={busy || !cid}
          onClick={() =>
            act(`/computers/${cid}/profile`, "PUT", {
              cpu,
              memory_gib: memory,
              storage_gib: storage,
              resolution,
              idle_timeout_minutes: idleTimeout,
            })
          }
        >
          Save resources
        </Button>
      </div>
      <p className="muted">
        CPU, memory, storage, display resolution, and idle stop apply on the
        next start.{" "}
        {quotaEnforced
          ? "The storage tier is a hard limit on this runtime."
          : "On this runtime the storage tier bounds clone copies and is shown against usage; it is not yet a hard disk limit."}
        Always on keeps background work running without an open dashboard.
        Runtime charges continue; credit exhaustion still stops the computer.
      </p>
      <label>
        New computer or template name{" "}
        <input
          aria-label="New computer or template name"
          maxLength={80}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Research environment"
        />
      </label>
      <p>
        Clones include files, browser sessions, and installed applications. Only
        clone a desktop into a workspace whose members may access those
        accounts.
      </p>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <Button
          disabled={busy || !cid || !name.trim()}
          onClick={() => act(`/computers/${cid}/clone`, "POST", { name })}
        >
          Clone computer
        </Button>
        <Button
          disabled={busy || !cid || !name.trim()}
          onClick={() => act(`/computers/${cid}/templates`, "POST", { name })}
        >
          Save system template
        </Button>
      </div>
      <p>
        System templates contain installed applications and system settings.
        They exclude your home folder, files, browser profile, and personal
        desktop preferences. They are private to this workspace.
      </p>
      <h3>Templates</h3>
      {!templates.length && <p>No templates yet.</p>}
      {templates.map((t) => (
        <div
          key={t.id}
          style={{
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <span>
            {t.name} · {t.status}
          </span>
          <Button
            disabled={busy || t.status !== "ready" || !name.trim()}
            onClick={() =>
              act(`/templates/${t.id}/computers`, "POST", { name })
            }
          >
            Create computer
          </Button>
          <Button
            disabled={busy || !["ready", "failed"].includes(t.status)}
            onClick={() => act(`/templates/${t.id}`, "DELETE")}
          >
            Delete template
          </Button>
        </div>
      ))}
      {message && <p role="status">{message}</p>}
      {jobs.length > 0 && (
        <div>
          <h3>Recent operations</h3>
          {jobs.slice(0, 6).map((j) => (
            <p key={j.id}>
              {j.kind.replaceAll("_", " ")} · {j.status}
              {j.error ? ` — ${j.error}` : ""}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
