"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "motion/react";
import {
  Monitor,
  Plus,
  Settings,
  CreditCard,
  ArrowUpRight,
  ArrowUp,
  ChevronDown,
  Folder,
  Terminal,
  Activity,
  Pause,
  Play,
  Power,
  MousePointer2,
  Check,
  Copy,
  LogOut,
  X,
  Loader2,
  KeyRound,
  Users,
  Gift,
  ArrowLeft,
  Trash2,
} from "lucide-react";
import {
  api,
  supabase,
  token,
  type Workspace,
  type Computer,
  type Run,
  type Activity as ActivityType,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Mark } from "@/components/brand";
import { Viewer } from "@/components/viewer";
type View = "computers" | "settings" | "billing";
export default function Dashboard() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [wid, setWid] = useState("");
  const [computers, setComputers] = useState<Computer[]>([]);
  const [selected, setSelected] = useState("");
  const [view, setView] = useState<View>("computers");
  const [events, setEvents] = useState<ActivityType[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("My computer");
  const [filePath, setFilePath] = useState("");
  const [tab, setTab] = useState("files");
  const [files, setFiles] = useState<
    { name: string; size: number; directory: boolean }[]
  >([]);
  const [command, setCommand] = useState("");
  const [output, setOutput] = useState("");
  const [key, setKey] = useState("");
  const [email, setEmail] = useState("");
  const [invite, setInvite] = useState("");
  const [members, setMembers] = useState<
    { id: string; email: string; role: string }[]
  >([]);
  const [entitlements, setEntitlements] = useState<any>(null);
  const workspace = workspaces.find((w) => w.id === wid);
  const computer = computers.find((c) => c.id === selected);
  const current = runs.find((r) =>
    ["queued", "running", "paused", "awaiting_approval"].includes(r.status),
  );
  const refresh = useCallback(async () => {
    const ws = await api<Workspace[]>("/workspaces");
    setWorkspaces(ws);
    const id = wid || ws[0]?.id;
    if (id) {
      if (!wid) setWid(id);
      setComputers(await api(`/workspaces/${id}/computers`));
    }
  }, [wid]);
  useEffect(() => {
    (async () => {
      if (!(await token())) {
        location.href = "/login";
        return;
      }
      try {
        await refresh();
        const v = new URLSearchParams(location.search).get("view");
        if (v === "billing" || v === "settings") setView(v);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setReady(true);
      }
    })();
  }, [refresh]);
  useEffect(() => {
    if (!wid) return;
    const id = setInterval(() => refresh().catch(() => {}), 4000);
    return () => clearInterval(id);
  }, [wid, refresh]);
  useEffect(() => {
    setEvents([]);
    setRuns([]);
    setFiles([]);
    setFilePath("");
    setOutput("");
    if (!selected) return;
    let done = false;
    let cursor = 0;
    let fetching = false;
    async function update() {
      if (fetching) return;
      fetching = true;
      try {
        const [e, r] = await Promise.all([
          api<ActivityType[]>(`/computers/${selected}/events?after=${cursor}`),
          api<Run[]>(`/computers/${selected}/runs`),
        ]);
        if (!done) {
          if (e.length) {
            cursor = e[e.length - 1].id;
            setEvents((old) => [...old, ...e].slice(-1000));
          }
          setRuns(r);
        }
      } catch {
      } finally {
        fetching = false;
      }
    }
    update();
    const id = setInterval(update, 2000);
    return () => {
      done = true;
      clearInterval(id);
    };
  }, [selected]);
  useEffect(() => {
    if (computer?.status === "running" && tab === "files")
      api(
        `/computers/${computer.id}/files?path=${encodeURIComponent(filePath)}`,
      )
        .then(setFiles)
        .catch(() => {});
  }, [computer?.id, computer?.status, tab, filePath]);
  useEffect(() => {
    if (!wid) return;
    if (view === "settings")
      api(`/workspaces/${wid}/members`)
        .then(setMembers)
        .catch(() => {});
    if (view === "billing")
      api(`/workspaces/${wid}/entitlements`)
        .then(setEntitlements)
        .catch(() => {});
  }, [wid, view]);
  async function openFile(file: { name: string; directory: boolean }) {
    const path = [filePath, file.name].filter(Boolean).join("/");
    if (file.directory) {
      setFilePath(path);
      return;
    }
    await perform(async () => {
      const data = await api<{ name: string; data: string }>(
        `/computers/${selected}/download?path=${encodeURIComponent(path)}`,
      );
      const bytes = Uint8Array.from(atob(data.data), (character) =>
        character.charCodeAt(0),
      );
      const url = URL.createObjectURL(new Blob([bytes]));
      const link = document.createElement("a");
      link.href = url;
      link.download = data.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const action = (a: string) =>
    perform(async () => {
      if (!computer) return;
      await api(`/computers/${computer.id}/actions/${a}`, "POST");
    });
  async function create(e: React.FormEvent) {
    e.preventDefault();
    await perform(async () => {
      const c = await api(`/workspaces/${wid}/computers`, "POST", { name });
      setSelected(c.id);
      setCreateOpen(false);
      await api(`/computers/${c.id}/actions/start`, "POST");
    });
  }
  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim() || !computer) return;
    await perform(async () => {
      await api(`/computers/${computer.id}/runs`, "POST", { prompt });
      setPrompt("");
      setRuns(await api(`/computers/${computer.id}/runs`));
      setEvents(await api(`/computers/${computer.id}/events`));
    });
  }
  function nav(v: View) {
    setView(v);
    setSelected("");
    setError("");
  }
  return (
    <div className="app-shell">
      <aside className="rail">
        <Link href="/" aria-label="Home">
          <Mark size={30} />
        </Link>
        <div className="rail-main">
          <button
            className={view === "computers" ? "active" : ""}
            title="Computers"
            aria-label="Computers"
            onClick={() => nav("computers")}
          >
            <Monitor size={20} />
          </button>
          <button
            className={view === "billing" ? "active" : ""}
            title="Billing"
            aria-label="Billing"
            onClick={() => nav("billing")}
          >
            <CreditCard size={20} />
          </button>
          <Link href="/trial" title="Token trial" aria-label="Token trial">
            <Gift size={20} />
          </Link>
        </div>
        <div className="rail-bottom">
          <button
            title="New computer"
            aria-label="New computer"
            onClick={() => setCreateOpen(true)}
          >
            <Plus size={20} />
          </button>
          <button
            className={view === "settings" ? "active" : ""}
            title="Settings"
            aria-label="Settings"
            onClick={() => nav("settings")}
          >
            <Settings size={20} />
          </button>
          <button
            title="Sign out"
            aria-label="Sign out"
            onClick={async () => {
              await supabase?.auth.signOut();
              location.href = "/";
            }}
          >
            <LogOut size={18} />
          </button>
          <span className="avatar">Y</span>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-header">
          <div className="breadcrumb">
            <select
              aria-label="Workspace"
              value={wid}
              onChange={(e) => {
                setWid(e.target.value);
                setSelected("");
              }}
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
            <span>/</span>
            <strong>
              {computer?.name ||
                (view === "computers"
                  ? "Computers"
                  : view === "billing"
                    ? "Billing"
                    : "Settings")}
            </strong>
          </div>
          <div className="header-right">
            <span className="credit-chip">
              <span className="status-dot green" />
              {Math.floor((workspace?.credits || 0) / 60)}h available
            </span>
            <Link href="/trial" className="small-link">
              Platform trial <ArrowUpRight size={13} />
            </Link>
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={15} />
            </button>
          </div>
        )}
        {!ready ? (
          <div className="page-loading">
            <Loader2 className="spin" />
            Opening your workspace…
          </div>
        ) : !workspace ? (
          <div className="onboarding">
            <Mark size={45} />
            <h1>Make a little space.</h1>
            <p>Create your first workspace to get started.</p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                perform(() => api("/workspaces", "POST", { name }));
              }}
            >
              <input
                aria-label="Workspace name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
              <Button disabled={busy}>
                Create workspace <ArrowUpRight size={16} />
              </Button>
            </form>
          </div>
        ) : view === "computers" && !computer ? (
          <section className="computers-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">YOUR WORKSPACE</div>
                <h1>Room for your next idea.</h1>
                <p>Your computers, ready when inspiration strikes.</p>
              </div>
              <Button onClick={() => setCreateOpen(true)}>
                <Plus size={16} />
                New computer
              </Button>
            </div>
            {!workspace.has_key && (
              <div className="setup-banner">
                <div>
                  <KeyRound size={18} />
                  <span>
                    <strong>Bring your agent to life.</strong> Connect your
                    Anthropic API key to start giving it tasks.
                  </span>
                </div>
                <button onClick={() => nav("settings")}>
                  Connect key <ArrowUpRight size={15} />
                </button>
              </div>
            )}
            <div className="computer-grid">
              {computers.map((c) => (
                <motion.button
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  key={c.id}
                  className="computer-card"
                  onClick={() => setSelected(c.id)}
                >
                  <div className="computer-thumbnail">
                    <div className="mini-landscape" />
                    <Monitor size={36} strokeWidth={1} />
                    <span className={"computer-state " + c.status}>
                      <span
                        className={
                          "status-dot " +
                          (c.status === "running" ? "green" : "")
                        }
                      />
                      {c.status}
                    </span>
                  </div>
                  <div className="computer-card-bottom">
                    <div>
                      <h3>{c.name}</h3>
                      <p>Linux · 2 vCPU · 4 GB RAM</p>
                    </div>
                    <ArrowUpRight size={18} />
                  </div>
                </motion.button>
              ))}
              <button
                className="new-computer-card"
                onClick={() => setCreateOpen(true)}
              >
                <span>
                  <Plus size={24} />
                </span>
                <h3>A fresh start.</h3>
                <p>Create a computer for your next project.</p>
              </button>
            </div>
            <div className="workspace-note">
              <Monitor size={16} />
              Computers keep their files when stopped. Agent tasks continue when
              you close this tab.
            </div>
          </section>
        ) : view === "computers" && computer ? (
          <section className="workspace-view">
            <div className="computer-column">
              <div className="computer-heading">
                <button
                  className="icon-button"
                  title="All computers"
                  aria-label="All computers"
                  onClick={() => setSelected("")}
                >
                  <ArrowLeft size={16} />
                </button>
                <span>{computer.name}</span>
                <div className="computer-actions">
                  {computer.status === "running" ? (
                    <>
                      <Button
                        variant="ghost"
                        disabled={
                          busy || computer.controller.startsWith("pending:")
                        }
                        onClick={() =>
                          action(
                            computer.controller === "agent"
                              ? "take-control"
                              : "resume",
                          )
                        }
                      >
                        <MousePointer2 size={14} />
                        {computer.controller === "agent"
                          ? "Take control"
                          : computer.controller.startsWith("pending:")
                            ? "Pausing agent…"
                            : "Return to agent"}
                      </Button>
                      <button
                        className="icon-button"
                        title="Stop computer"
                        aria-label="Stop computer"
                        onClick={() => action("stop")}
                      >
                        <Power size={16} />
                      </button>
                    </>
                  ) : (
                    <Button
                      variant="ghost"
                      disabled={
                        busy ||
                        ["starting", "stopping"].includes(computer.status)
                      }
                      onClick={() => action("start")}
                    >
                      <Play size={14} />
                      Start
                    </Button>
                  )}
                </div>
              </div>
              <Viewer computer={computer} onStart={() => action("start")} />
              <div className="bottom-panel">
                <div className="tab-list" role="tablist">
                  {[
                    ["files", Folder],
                    ["terminal", Terminal],
                    ["activity", Activity],
                  ].map(([label, Icon]) => {
                    const I = Icon as typeof Folder;
                    return (
                      <button
                        key={String(label)}
                        role="tab"
                        aria-selected={tab === label}
                        className={tab === label ? "selected" : ""}
                        onClick={() => setTab(String(label))}
                      >
                        <I size={14} />
                        {String(label)}
                      </button>
                    );
                  })}
                </div>
                {tab === "files" ? (
                  <div className="file-list">
                    <div className="path-label">
                      <button onClick={() => setFilePath("")}>⌂ Home</button>
                      <span>/ {filePath}</span>
                      {filePath && (
                        <button
                          onClick={() =>
                            setFilePath(
                              filePath.split("/").slice(0, -1).join("/"),
                            )
                          }
                        >
                          Up one folder
                        </button>
                      )}
                    </div>
                    {files.length ? (
                      files.map((f) => (
                        <button
                          className="file-row"
                          key={f.name}
                          onClick={() => openFile(f)}
                          disabled={busy}
                          title={f.directory ? "Open folder" : "Download file"}
                        >
                          <Folder size={16} />
                          <span>{f.name}</span>
                          <small>
                            {f.directory ? "Folder" : `${f.size} B`}
                          </small>
                        </button>
                      ))
                    ) : (
                      <div className="panel-empty">
                        {computer.status === "running"
                          ? "Files will appear here as you work."
                          : "Start your computer to browse its files."}
                      </div>
                    )}
                  </div>
                ) : tab === "terminal" ? (
                  <div className="terminal-panel">
                    <pre>
                      {output ||
                        "Take control to run commands in your computer."}
                    </pre>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        perform(async () => {
                          const r = await api(
                            `/computers/${selected}/terminal`,
                            "POST",
                            { command },
                          );
                          setOutput(
                            (old) => old + "\n$ " + command + "\n" + r.output,
                          );
                          setCommand("");
                        });
                      }}
                    >
                      <span>❯</span>
                      <input
                        aria-label="Terminal command"
                        value={command}
                        onChange={(e) => setCommand(e.target.value)}
                        placeholder="Enter a command…"
                        disabled={computer.controller === "agent"}
                      />
                      <button
                        disabled={busy || !command}
                        aria-label="Run command"
                      >
                        <ArrowUp size={16} />
                      </button>
                    </form>
                  </div>
                ) : (
                  <div className="activity-list">
                    {events
                      .filter((e) => !["assistant", "user"].includes(e.kind))
                      .map((e) => (
                        <div key={e.id}>
                          <span className="status-dot" />
                          {e.text}
                        </div>
                      ))}
                    {!events.length && (
                      <div className="panel-empty">
                        A fresh computer. Activity will appear here.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            <aside className="chat-panel">
              <div className="chat-heading">
                <span>
                  <Mark size={19} />
                  Your agent
                </span>
                <span className="tiny-label">CLAUDE</span>
              </div>
              <div className="chat-messages">
                {!events.some((e) =>
                  ["user", "assistant"].includes(e.kind),
                ) && (
                  <div className="chat-welcome">
                    <Mark size={36} />
                    <h2>
                      What are we
                      <br />
                      working on today?
                    </h2>
                    <p>
                      Give your agent a task.
                      <br />
                      It has a whole computer to work with.
                    </p>
                    <div className="prompt-suggestions">
                      {[
                        "Research a topic and save a summary",
                        "Organize the files in my workspace",
                        "Build a simple webpage",
                      ].map((p) => (
                        <button key={p} onClick={() => setPrompt(p)}>
                          {p}
                          <ArrowUpRight size={13} />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {events
                  .filter((e) =>
                    ["user", "assistant", "error", "approval"].includes(e.kind),
                  )
                  .map((e) => (
                    <div key={e.id} className={"message " + e.kind}>
                      <span>
                        {e.kind === "user"
                          ? "You"
                          : e.kind === "approval"
                            ? "Approval needed"
                            : "Agent"}
                      </span>
                      <p>{e.text}</p>
                    </div>
                  ))}
                {current?.status === "awaiting_approval" && (
                  <div className="approval-card">
                    <strong>Your approval is needed</strong>
                    <p>{current.approval?.action}</p>
                    <div>
                      <Button
                        disabled={busy}
                        onClick={() =>
                          perform(() =>
                            api(`/runs/${current.id}/approve`, "POST"),
                          )
                        }
                      >
                        Approve
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() =>
                          perform(() =>
                            api(`/runs/${current.id}/reject`, "POST"),
                          )
                        }
                      >
                        Decline
                      </Button>
                    </div>
                  </div>
                )}
                {current && (
                  <div className="run-status">
                    <span className="status-dot green" />
                    {current.status.replaceAll("_", " ")} · {current.steps}{" "}
                    steps
                    <button
                      onClick={() =>
                        perform(() => api(`/runs/${current.id}/cancel`, "POST"))
                      }
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>
              <form className="composer" onSubmit={send}>
                <textarea
                  aria-label="Task instructions"
                  placeholder="Ask about this computer…"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send(e);
                    }
                  }}
                />
                <div>
                  <span>
                    Claude Sonnet <ChevronDown size={12} />
                  </span>
                  <button
                    aria-label="Send task"
                    disabled={
                      busy ||
                      !prompt.trim() ||
                      !!current ||
                      computer.status !== "running"
                    }
                  >
                    <ArrowUp size={18} />
                  </button>
                </div>
              </form>
              <p className="chat-footnote">
                Important external actions require your approval.
              </p>
            </aside>
          </section>
        ) : view === "settings" ? (
          <section className="settings-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">MAKE IT YOURS</span>
                <h1>Workspace settings</h1>
                <p>The right tools, the right people.</p>
              </div>
            </div>
            <article className="settings-card">
              <div className="card-title">
                <KeyRound size={20} />
                <div>
                  <h2>Anthropic API key</h2>
                  <p>Your AI usage is billed directly by Anthropic.</p>
                </div>
                <span className="tag">
                  {workspace.has_key ? "CONNECTED" : "NOT CONNECTED"}
                </span>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  perform(async () => {
                    await api(`/workspaces/${wid}/credential`, "PUT", { key });
                    setKey("");
                  });
                }}
              >
                <label htmlFor="api-key">API key</label>
                <div className="inline-form">
                  <input
                    id="api-key"
                    type="password"
                    autoComplete="off"
                    placeholder={
                      workspace.has_key
                        ? "Enter a new key to replace your saved key"
                        : "sk-ant-…"
                    }
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    required
                  />
                  <Button disabled={busy || workspace.role !== "owner"}>
                    Save key
                  </Button>
                </div>
              </form>
              <p className="field-note">
                Encrypted at rest. Your key is never placed inside the cloud
                computer.
              </p>
              {workspace.has_key && workspace.role === "owner" && (
                <button
                  className="text-link"
                  onClick={() =>
                    perform(() =>
                      api(`/workspaces/${wid}/credential`, "DELETE"),
                    )
                  }
                >
                  Remove key
                </button>
              )}
            </article>
            <article className="settings-card">
              <div className="card-title">
                <Users size={20} />
                <div>
                  <h2>People in your workspace</h2>
                  <p>Good work is better together. Up to three members.</p>
                </div>
              </div>
              {members.map((m) => (
                <div className="member-row" key={m.id}>
                  <span className="avatar">{m.email[0]?.toUpperCase()}</span>
                  <span>{m.email}</span>
                  <span className="tag">{m.role}</span>
                  {m.role !== "owner" && workspace.role === "owner" && (
                    <button
                      aria-label={`Remove ${m.email}`}
                      onClick={() =>
                        perform(async () => {
                          await api(
                            `/workspaces/${wid}/members/${m.id}`,
                            "DELETE",
                          );
                          setMembers(await api(`/workspaces/${wid}/members`));
                        })
                      }
                    >
                      <X size={15} />
                    </button>
                  )}
                </div>
              ))}
              <form
                className="inline-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  perform(async () => {
                    const r = await api(
                      `/workspaces/${wid}/invitations`,
                      "POST",
                      { email },
                    );
                    setInvite(r.url);
                    setEmail("");
                  });
                }}
              >
                <input
                  type="email"
                  aria-label="Invite email"
                  placeholder="teammate@company.com"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <Button
                  variant="ghost"
                  disabled={busy || workspace.role !== "owner"}
                >
                  Create invite
                </Button>
              </form>
              {invite && (
                <div className="invite-link">
                  <span>{invite}</span>
                  <button
                    aria-label="Copy invitation"
                    onClick={() => navigator.clipboard.writeText(invite)}
                  >
                    <Copy size={16} />
                  </button>
                </div>
              )}
            </article>
          </section>
        ) : (
          <section className="settings-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">YOUR PLAN</span>
                <h1>A little room to grow.</h1>
                <p>Simple pricing. No surprises.</p>
              </div>
            </div>
            <div className="billing-grid">
              <article className="settings-card">
                <span className="tiny-label">STARTER</span>
                <div className="billing-price">
                  $29<span>/month</span>
                </div>
                <p>100 computer-hours · 2 saved computers · 3 members</p>
                <div className="usage-bar">
                  <i
                    style={{
                      width: `${Math.min(100, (workspace.credits / 6000) * 100)}%`,
                    }}
                  />
                </div>
                <p className="usage-caption">
                  {(workspace.credits / 60).toFixed(1)} hours remaining{" "}
                  <span>{workspace.subscription}</span>
                </p>
                <Button
                  disabled={busy}
                  onClick={() =>
                    perform(async () => {
                      const r = await api(
                        `/workspaces/${wid}/billing/${workspace.subscription === "active" ? "portal" : "subscription"}`,
                        "POST",
                      );
                      location.href = r.url;
                    })
                  }
                >
                  {workspace.subscription === "active"
                    ? "Manage subscription"
                    : "Subscribe to Starter"}
                  <ArrowUpRight size={15} />
                </Button>
              </article>
              <article className="settings-card">
                <span className="tiny-label">KEEP GOING</span>
                <h2>More time for your ideas.</h2>
                <p>
                  Add 50 computer-hours for $10.
                  <br />
                  Top-ups carry forward while subscribed.
                </p>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    perform(async () => {
                      const r = await api(
                        `/workspaces/${wid}/billing/topup`,
                        "POST",
                      );
                      location.href = r.url;
                    })
                  }
                >
                  Add 50 hours <Plus size={15} />
                </Button>
                <Link className="text-link" href="/trial">
                  <Gift size={15} />
                  Explore token-holder trials
                </Link>
              </article>
            </div>
            {entitlements?.trials?.map((t: any) => (
              <div className="setup-banner" key={t.service}>
                <span>
                  {t.service} trial · {t.active ? "Active" : "Expired or used"}{" "}
                  · Ends {new Date(t.expires_at + "Z").toLocaleDateString()}
                </span>
              </div>
            ))}
          </section>
        )}
      </div>
      <Dialog.Root open={createOpen} onOpenChange={setCreateOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog">
            <Dialog.Close className="dialog-close" aria-label="Close">
              <X size={18} />
            </Dialog.Close>
            <div className="monitor-icon">
              <Monitor size={30} />
            </div>
            <Dialog.Title>A computer of your own.</Dialog.Title>
            <Dialog.Description>
              Start with a clean Linux desktop. Make it yours.
            </Dialog.Description>
            <form onSubmit={create}>
              <label>
                Computer name
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={80}
                  autoFocus
                />
              </label>
              <div className="specs">
                <span>Linux</span>
                <span>2 vCPU</span>
                <span>4 GB RAM</span>
                <span>Persistent home</span>
              </div>
              <Button disabled={busy || !wid}>
                {busy ? (
                  <Loader2 className="spin" size={16} />
                ) : (
                  <Plus size={16} />
                )}
                Create computer
              </Button>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
