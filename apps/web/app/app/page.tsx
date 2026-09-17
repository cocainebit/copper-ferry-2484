"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CryptoBilling } from "@/components/crypto-billing";
import { PlatformFeatures } from "@/components/platform-features";
import { ServiceSetup } from "@/components/service-setup";
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
  Pencil,
  Package,
  Timer,
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
import { TerminalPanel } from "@/components/terminal";
import { ApiKeys } from "@/components/api-keys";
import { Secrets } from "@/components/secrets";
import { AppsPanel } from "@/components/apps";
import { TemplateRegistry } from "@/components/template-registry";
import { AutomationsPanel } from "@/components/automations";
import { Fleet } from "@/components/fleet";
type CreationTemplate = {
  id: string;
  name: string;
  version?: number | null;
  requires_secrets?: string[];
  status: string;
  cpu: number;
  memory_gib: number;
  storage_gib: number;
  resolution: string;
  idle_timeout_minutes: number;
};
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
  const [createCpu, setCreateCpu] = useState(2);
  const [createMemory, setCreateMemory] = useState(4);
  const [createStorage, setCreateStorage] = useState(20);
  const [createResolution, setCreateResolution] = useState("1440x900");
  const [createIdleTimeout, setCreateIdleTimeout] = useState(15);
  const [createTemplate, setCreateTemplate] = useState("");
  const [creationTemplates, setCreationTemplates] = useState<
    CreationTemplate[]
  >([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesError, setTemplatesError] = useState("");
  const [creationError, setCreationError] = useState("");
  const [creating, setCreating] = useState(false);
  const creationLock = useRef(false);
  const [name, setName] = useState("My computer");
  const [filePath, setFilePath] = useState("");
  const [tab, setTab] = useState("files");
  const [files, setFiles] = useState<
    { name: string; size: number; directory: boolean }[]
  >([]);
  const [command, setCommand] = useState("");
  const [output, setOutput] = useState("");
  const [terminalNote, setTerminalNote] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const terminalUnavailable = useCallback(
    (reason: string) => setTerminalNote(reason),
    [],
  );
  const [key, setKey] = useState("");
  const [email, setEmail] = useState("");
  const [invite, setInvite] = useState("");
  const [members, setMembers] = useState<
    { id: string; email: string; role: string }[]
  >([]);
  const [entitlements, setEntitlements] = useState<any>(null);
  const workspace = workspaces.find((w) => w.id === wid);
  useEffect(() => {
    if (!createOpen) return;
    let active = true;
    setCreateTemplate("");
    setCreationTemplates([]);
    setCreateCpu(2);
    setCreateMemory(4);
    setCreateStorage(20);
    setCreateResolution("1440x900");
    setCreateIdleTimeout(15);
    setCreationError("");
    setTemplatesError("");
    if (workspace?.role !== "owner") {
      setTemplatesLoading(false);
      return;
    }
    setTemplatesLoading(true);
    api<CreationTemplate[]>(`/workspaces/${wid}/templates`)
      .then((result) => {
        if (active)
          setCreationTemplates(result.filter((t) => t.status === "ready"));
      })
      .catch((e) => {
        if (active) setTemplatesError(e.message);
      })
      .finally(() => {
        if (active) setTemplatesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [createOpen, wid, workspace?.role]);
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
    setTerminalNote("");
    setRenaming(false);
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
    if (creationLock.current || !wid || !name.trim()) return;
    creationLock.current = true;
    setCreating(true);
    setCreationError("");
    const body = {
      name: name.trim(),
      cpu: createCpu,
      memory_gib: createMemory,
      storage_gib: createStorage,
      resolution: createResolution,
      idle_timeout_minutes: createIdleTimeout,
    };
    try {
      const result = createTemplate
        ? await api<{ target_id: string }>(
            `/templates/${createTemplate}/computers`,
            "POST",
            body,
          )
        : await api<Computer>(`/workspaces/${wid}/computers`, "POST", body);
      const computerId = "target_id" in result ? result.target_id : result.id;
      setSelected(computerId);
      setView("computers");
      setCreateOpen(false);
      // The template worker will leave the copied computer stopped when ready.
      if (!createTemplate) {
        try {
          await api(`/computers/${computerId}/actions/start`, "POST");
        } catch (e) {
          setError((e as Error).message);
        }
      }
      await refresh();
    } catch (e) {
      setCreationError((e as Error).message);
    } finally {
      creationLock.current = false;
      setCreating(false);
    }
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
            <Fleet
              workspaceId={wid}
              workspaces={workspaces}
              owner={workspace.role === "owner"}
              onOpen={(id) => setSelected(id)}
              onCreate={() => setCreateOpen(true)}
              onChanged={() => refresh().catch(() => {})}
            />
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
                {renaming ? (
                  <form
                    className="rename-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const name = renameValue.trim();
                      if (!name || name === computer.name) {
                        setRenaming(false);
                        return;
                      }
                      perform(async () => {
                        await api(`/computers/${computer.id}`, "PATCH", {
                          name,
                        });
                        setRenaming(false);
                      });
                    }}
                  >
                    <input
                      aria-label="Computer name"
                      value={renameValue}
                      maxLength={80}
                      autoFocus
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setRenaming(false);
                      }}
                    />
                    <Button variant="ghost" disabled={busy}>
                      <Check size={13} /> Save
                    </Button>
                  </form>
                ) : (
                  <>
                    <span>{computer.name}</span>
                    <button
                      className="icon-button subtle"
                      title="Rename computer"
                      aria-label="Rename computer"
                      onClick={() => {
                        setRenameValue(computer.name);
                        setRenaming(true);
                      }}
                    >
                      <Pencil size={13} />
                    </button>
                  </>
                )}
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
                        [
                          "starting",
                          "stopping",
                          "copying",
                          "customizing",
                          "copy_failed",
                        ].includes(computer.status)
                      }
                      onClick={() => action("start")}
                    >
                      <Play size={14} />
                      Start
                    </Button>
                  )}
                </div>
              </div>
              <Viewer
                computer={computer}
                onStart={() => action("start")}
                owner={workspace.role === "owner"}
              />
              <div className="bottom-panel">
                <div className="tab-list" role="tablist">
                  {[
                    ["files", Folder],
                    ["terminal", Terminal],
                    ["apps", Package],
                    ["automations", Timer],
                    ["activity", Activity],
                  ].map(([label, Icon]) => {
                    const I = Icon as typeof Folder;
                    return (
                      <button
                        key={String(label)}
                        role="tab"
                        aria-selected={tab === label}
                        className={tab === label ? "selected" : ""}
                        onClick={() => {
                          // Re-opening the terminal tab retries the interactive shell.
                          if (label === "terminal") setTerminalNote("");
                          setTab(String(label));
                        }}
                      >
                        <I size={14} />
                        {String(label)}
                      </button>
                    );
                  })}
                </div>
                {tab === "files" ? (
                  <div className="file-list">
                    <label className="file-upload">
                      Upload file
                      <input
                        type="file"
                        aria-label="Upload file"
                        disabled={busy || computer.controller === "agent"}
                        onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          if (file.size > 20 * 1024 * 1024) {
                            setError("Uploads must be no larger than 20 MB.");
                            e.target.value = "";
                            return;
                          }
                          await perform(async () => {
                            const data = await new Promise<string>(
                              (resolve, reject) => {
                                const reader = new FileReader();
                                reader.onload = () =>
                                  resolve(
                                    String(reader.result).split(",", 2)[1] ||
                                      "",
                                  );
                                reader.onerror = () =>
                                  reject(new Error("Could not read file"));
                                reader.readAsDataURL(file);
                              },
                            );
                            await api(`/computers/${selected}/upload`, "POST", {
                              path: file.name,
                              data,
                            });
                            const refreshed = await api<typeof files>(
                              `/computers/${selected}/files?path=${encodeURIComponent(filePath)}`,
                            );
                            setFiles(refreshed);
                          });
                          e.target.value = "";
                        }}
                      />
                    </label>
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
                          {!f.directory && (
                            <span
                              role="button"
                              tabIndex={0}
                              aria-label={`Delete ${f.name}`}
                              className="file-delete"
                              onClick={async (e) => {
                                e.stopPropagation();
                                if (!window.confirm(`Delete ${f.name}?`))
                                  return;
                                await perform(async () => {
                                  await api(
                                    `/computers/${selected}/delete-file`,
                                    "POST",
                                    {
                                      path: [filePath, f.name]
                                        .filter(Boolean)
                                        .join("/"),
                                    },
                                  );
                                  const refreshed = await api<typeof files>(
                                    `/computers/${selected}/files?path=${encodeURIComponent(filePath)}`,
                                  );
                                  setFiles(refreshed);
                                });
                              }}
                            >
                              <Trash2 size={13} />
                            </span>
                          )}
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
                  computer.status === "running" &&
                  computer.controller !== "agent" &&
                  !computer.controller.startsWith("pending:") &&
                  !terminalNote ? (
                    <TerminalPanel
                      key={computer.id}
                      computerId={computer.id}
                      onUnavailable={terminalUnavailable}
                    />
                  ) : (
                    <div className="terminal-panel">
                      <pre>
                        {output ||
                          terminalNote ||
                          (computer.status === "running"
                            ? "Take control to open an interactive shell in your computer."
                            : "Start your computer and take control to open a shell.")}
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
                  )
                ) : tab === "automations" ? (
                  <AutomationsPanel
                    key={computer.id}
                    computer={computer}
                    owner={workspace.role === "owner"}
                  />
                ) : tab === "apps" ? (
                  <AppsPanel
                    key={computer.id}
                    computer={computer}
                    owner={workspace.role === "owner"}
                  />
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
            {workspace.role === "owner" && (
              <>
                <article className="settings-card">
                  <ServiceSetup workspaceId={wid} />
                </article>
                <PlatformFeatures
                  workspaceId={wid}
                  computers={computers}
                  onRefresh={refresh}
                />
                <TemplateRegistry workspaceId={wid} />
                <Secrets workspaceId={wid} />
                <ApiKeys workspaceId={wid} />
              </>
            )}
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
          <>
            <CryptoBilling
              key={wid}
              workspaceId={wid}
              owner={workspace.role === "owner"}
            />
            {entitlements?.trials?.map(
              (trial: {
                service: string;
                active: boolean;
                expires_at: string;
              }) => (
                <div className="setup-banner" key={trial.service}>
                  <span>
                    {trial.service === "agent-desktop"
                      ? "Cubicle"
                      : trial.service}{" "}
                    trial · {trial.active ? "Active" : "Expired or used"} · Ends{" "}
                    {new Date(
                      trial.expires_at.endsWith("Z") ||
                        trial.expires_at.includes("+")
                        ? trial.expires_at
                        : trial.expires_at + "Z",
                    ).toLocaleDateString()}
                  </span>
                </div>
              ),
            )}
          </>
        )}
      </div>
      <Dialog.Root
        open={createOpen}
        onOpenChange={(open) => {
          if (!creationLock.current) setCreateOpen(open);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog">
            <Dialog.Close
              className="dialog-close"
              aria-label="Close"
              disabled={creating}
            >
              <X size={18} />
            </Dialog.Close>
            <div className="monitor-icon">
              <Monitor size={30} />
            </div>
            <Dialog.Title>A computer of your own.</Dialog.Title>
            <Dialog.Description>
              Choose your Linux environment and resources. Your home files
              persist across restarts.
            </Dialog.Description>
            <form onSubmit={create}>
              <label>
                Computer name
                <input
                  value={name}
                  disabled={creating}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={80}
                  autoFocus
                />
              </label>
              <label>
                Starting environment
                <select
                  value={createTemplate}
                  disabled={
                    creating ||
                    templatesLoading ||
                    workspace?.role !== "owner" ||
                    !!templatesError
                  }
                  onChange={(e) => {
                    setCreateTemplate(e.target.value);
                    const template = creationTemplates.find(
                      (t) => t.id === e.target.value,
                    );
                    setCreateCpu(template?.cpu || 2);
                    setCreateMemory(template?.memory_gib || 4);
                    setCreateStorage(template?.storage_gib || 20);
                    setCreateResolution(template?.resolution || "1440x900");
                    setCreateIdleTimeout(template?.idle_timeout_minutes ?? 15);
                  }}
                >
                  <option value="">Clean Linux desktop</option>
                  {creationTemplates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                      {t.version ? ` v${t.version}` : ""}
                      {t.requires_secrets?.length
                        ? ` (needs ${t.requires_secrets.join(", ")})`
                        : ""}
                    </option>
                  ))}
                </select>
              </label>
              {templatesLoading && (
                <p className="muted">Loading workspace templates…</p>
              )}
              {templatesError && (
                <p role="status" className="muted">
                  Templates unavailable: {templatesError}. You can still create
                  a clean desktop.
                </p>
              )}
              {workspace?.role !== "owner" && (
                <p className="muted">
                  Workspace owners can create computers from templates.
                </p>
              )}
              <div className="creation-resources">
                <label>
                  CPU
                  <select
                    aria-label="CPU"
                    value={createCpu}
                    disabled={creating}
                    onChange={(e) => setCreateCpu(Number(e.target.value))}
                  >
                    <option value={1}>1 vCPU</option>
                    <option value={2}>2 vCPU</option>
                  </select>
                </label>
                <label>
                  Memory
                  <select
                    aria-label="Memory"
                    value={createMemory}
                    disabled={creating}
                    onChange={(e) => setCreateMemory(Number(e.target.value))}
                  >
                    <option value={2}>2 GiB RAM</option>
                    <option value={4}>4 GiB RAM</option>
                  </select>
                </label>
                <label>
                  Storage
                  <select
                    aria-label="Storage"
                    value={createStorage}
                    disabled={creating}
                    onChange={(e) => setCreateStorage(Number(e.target.value))}
                  >
                    <option value={20}>20 GiB</option>
                    <option value={50}>50 GiB</option>
                    <option value={100}>100 GiB</option>
                  </select>
                </label>
              </div>
              <label>
                Display resolution
                <select
                  aria-label="Display resolution"
                  value={createResolution}
                  disabled={creating}
                  onChange={(e) => setCreateResolution(e.target.value)}
                >
                  <option value="1280x720">1280 × 720</option>
                  <option value="1440x900">1440 × 900</option>
                  <option value="1920x1080">1920 × 1080</option>
                </select>
              </label>
              <label>
                Idle stop
                <select
                  aria-label="Idle stop"
                  value={createIdleTimeout}
                  disabled={creating}
                  onChange={(e) => setCreateIdleTimeout(Number(e.target.value))}
                >
                  <option value={5}>After 5 minutes</option>
                  <option value={15}>After 15 minutes</option>
                  <option value={30}>After 30 minutes</option>
                  <option value={60}>After 1 hour</option>
                  <option value={0}>Always on</option>
                  {![0, 5, 15, 30, 60].includes(createIdleTimeout) && (
                    <option value={createIdleTimeout}>
                      After {createIdleTimeout} minutes
                    </option>
                  )}
                </select>
              </label>
              <p className="muted creation-note">
                Always on keeps background work running without an open
                dashboard. Runtime charges continue; the computer still stops
                when credits run out.
              </p>
              <p className="muted creation-note">
                {createTemplate
                  ? "Templates copy installed software and system settings into a fresh home directory. Start the computer once its copy is ready."
                  : "Linux desktop with a browser and terminal. Install tools and customize it after starting."}
              </p>
              {creationError && (
                <p role="alert" className="error-banner">
                  {creationError}
                </p>
              )}
              <Button disabled={busy || creating || !wid}>
                {creating ? (
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
