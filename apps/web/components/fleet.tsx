"use client";
import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  Monitor,
  ArrowUpRight,
  Plus,
  Search,
  Tag,
  Play,
  Power,
} from "lucide-react";
import { api, type Workspace } from "@/lib/api";
import { Button } from "@/components/ui/button";

type FleetComputer = {
  id: string;
  name: string;
  status: string;
  error: string | null;
  labels: string[];
  cpu: number;
  memory_gib: number;
  storage_gib: number;
  resolution: string;
  os: string;
  gpu: number;
  screens: number;
  automations: number;
  usage_24h_minutes: number;
};
type Summary = {
  by_status: Record<string, number>;
  saved: number;
  running: number;
  limits: { plan: string; saved: number; running: number };
  host: { max_desktops: number; in_use: number };
  usage_24h_minutes: number;
  spend_24h_micro_usdc: number;
  labels: string[];
};

const hours = (minutes: number) =>
  minutes < 60 ? `${minutes} min` : `${(minutes / 60).toFixed(1)} h`;

export function Fleet({
  workspaceId,
  workspaces,
  owner,
  onOpen,
  onCreate,
  onChanged,
}: {
  workspaceId: string;
  workspaces: Workspace[];
  owner: boolean;
  onOpen: (id: string) => void;
  onCreate: () => void;
  onChanged: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [computers, setComputers] = useState<FleetComputer[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [label, setLabel] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [newLabel, setNewLabel] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const params = new URLSearchParams({ q: query, status, label });
    const body = await api<{ summary: Summary; computers: FleetComputer[] }>(
      `/workspaces/${workspaceId}/fleet?${params}`,
    );
    setSummary(body.summary);
    setComputers(body.computers);
    setSelected((old) =>
      old.filter((id) => body.computers.some((c) => c.id === id)),
    );
  }, [workspaceId, query, status, label]);
  useEffect(() => {
    load().catch((e) => setMessage(e.message));
    const timer = setInterval(() => load().catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [load]);
  async function bulk(action: string, extra: Record<string, string> = {}) {
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{
        succeeded: number;
        results: { id: string; ok: boolean; error?: string }[];
      }>(`/workspaces/${workspaceId}/computers/bulk`, "POST", {
        ids: selected,
        action,
        ...extra,
      });
      const failures = result.results.filter((r) => !r.ok);
      setMessage(
        `${result.succeeded} of ${result.results.length} done` +
          (failures.length
            ? ` · ${failures
                .map(
                  (f) =>
                    `${computers.find((c) => c.id === f.id)?.name || f.id}: ${f.error}`,
                )
                .join("; ")}`
            : ""),
      );
      await load();
      onChanged();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function move(id: string, target: string) {
    setBusy(true);
    setMessage("");
    try {
      await api(`/computers/${id}/move`, "POST", { workspace_id: target });
      setMessage("Computer moved.");
      await load();
      onChanged();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const ownedElsewhere = workspaces.filter(
    (w) => w.id !== workspaceId && w.role === "owner",
  );
  const toggle = (id: string) =>
    setSelected((old) =>
      old.includes(id) ? old.filter((x) => x !== id) : [...old, id],
    );
  return (
    <>
      {summary && (
        <div className="fleet-summary">
          <div>
            <strong>
              {summary.running}/{summary.limits.running}
            </strong>
            <span>running</span>
          </div>
          <div>
            <strong>
              {summary.saved}/{summary.limits.saved}
            </strong>
            <span>saved ({summary.limits.plan} plan)</span>
          </div>
          <div>
            <strong>{hours(summary.usage_24h_minutes)}</strong>
            <span>metered, last 24 h</span>
          </div>
          <div>
            <strong>
              {(summary.spend_24h_micro_usdc / 1_000_000).toFixed(2)} USDC
            </strong>
            <span>credit spend, last 24 h</span>
          </div>
          <div>
            <strong>
              {summary.host.in_use}/{summary.host.max_desktops}
            </strong>
            <span>host capacity in use</span>
          </div>
        </div>
      )}
      <div className="fleet-filters">
        <label className="fleet-search">
          <Search size={13} />
          <input
            aria-label="Search computers"
            placeholder="Search by name or label"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="Filter by status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All statuses</option>
          {Object.entries(summary?.by_status || {}).map(([s, n]) => (
            <option key={s} value={s}>
              {s} ({n})
            </option>
          ))}
        </select>
        {summary?.labels.map((l) => (
          <button
            key={l}
            className={"label-chip " + (label === l ? "selected" : "")}
            onClick={() => setLabel(label === l ? "" : l)}
          >
            <Tag size={10} /> {l}
          </button>
        ))}
      </div>
      {selected.length > 0 && (
        <div className="fleet-bulk" role="toolbar" aria-label="Bulk actions">
          <span>{selected.length} selected</span>
          <Button variant="ghost" disabled={busy} onClick={() => bulk("start")}>
            <Play size={13} /> Start
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => bulk("stop")}>
            <Power size={13} /> Stop
          </Button>
          <input
            aria-label="Label for selected computers"
            placeholder="label"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value.toLowerCase())}
          />
          <Button
            variant="ghost"
            disabled={busy || !newLabel}
            onClick={() => bulk("add_label", { label: newLabel })}
          >
            Add label
          </Button>
          <Button
            variant="ghost"
            disabled={busy || !newLabel}
            onClick={() => bulk("remove_label", { label: newLabel })}
          >
            Remove label
          </Button>
          <button className="text-link" onClick={() => setSelected([])}>
            Clear
          </button>
        </div>
      )}
      {message && (
        <p role="status" className="field-note">
          {message}
        </p>
      )}
      <div className="computer-grid">
        {computers.map((c) => (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            key={c.id}
            className={
              "fleet-card " + (selected.includes(c.id) ? "selected" : "")
            }
          >
            <input
              type="checkbox"
              className="fleet-select"
              aria-label={`Select ${c.name}`}
              checked={selected.includes(c.id)}
              onChange={() => toggle(c.id)}
            />
            <button className="computer-card" onClick={() => onOpen(c.id)}>
              <div className="computer-thumbnail">
                <div className="mini-landscape" />
                <Monitor size={36} strokeWidth={1} />
                <span className={"computer-state " + c.status}>
                  <span
                    className={
                      "status-dot " + (c.status === "running" ? "green" : "")
                    }
                  />
                  {c.status}
                </span>
              </div>
              <div className="computer-card-bottom">
                <div>
                  <h3>{c.name}</h3>
                  <p>
                    {c.os === "windows" ? "Windows" : "Linux"} · {c.cpu} vCPU ·{" "}
                    {c.memory_gib} GiB RAM · {c.storage_gib} GiB
                    {c.gpu ? ` · ${c.gpu} GPU` : ""}
                  </p>
                  <p>
                    {hours(c.usage_24h_minutes)} today
                    {c.screens > 1 ? ` · ${c.screens} screens` : ""}
                    {c.automations
                      ? ` · ${c.automations} automation${c.automations === 1 ? "" : "s"}`
                      : ""}
                  </p>
                  {c.error && <p className="fleet-error">{c.error}</p>}
                  {c.labels.length > 0 && (
                    <div className="fleet-labels">
                      {c.labels.map((l) => (
                        <span key={l} className="label-chip static">
                          {l}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <ArrowUpRight size={18} />
              </div>
            </button>
            {owner && ownedElsewhere.length > 0 && c.status === "stopped" && (
              <select
                className="fleet-move"
                aria-label={`Move ${c.name} to another workspace`}
                value=""
                disabled={busy}
                onChange={(e) => e.target.value && move(c.id, e.target.value)}
              >
                <option value="">Move to…</option>
                {ownedElsewhere.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            )}
          </motion.div>
        ))}
        <button className="new-computer-card" onClick={onCreate}>
          <span>
            <Plus size={24} />
          </span>
          <h3>A fresh start.</h3>
          <p>Create a computer for your next project.</p>
        </button>
      </div>
    </>
  );
}
