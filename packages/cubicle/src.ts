/** Cubicle SDK: drive cloud computers with a workspace API key. Works in Node 18+ and browsers. */

export type ComputerInfo = {
  id: string;
  name: string;
  workspace_id: string;
  status: string;
  controller: string;
  error: string | null;
  created_at: string;
  cpu: number;
  memory_gib: number;
  storage_gib: number;
  resolution: string;
  idle_timeout_minutes?: number;
};
export type Workspace = {
  id: string;
  name: string;
  role: string;
  credits: number;
  balance_micro_usdc: number;
};
export type Screenshot = {
  format: "png";
  width: number;
  height: number;
  /** Base64 PNG. */
  image: string;
};
export type FileEntry = { name: string; size: number; directory: boolean };
export type CreateOptions = {
  name: string;
  cpu?: 1 | 2;
  memory_gib?: 2 | 4;
  storage_gib?: 20 | 50 | 100;
  resolution?: "1280x720" | "1440x900" | "1920x1080";
  idle_timeout_minutes?: number;
};
export type ClickOptions = {
  button?: "left" | "right" | "middle";
  count?: 1 | 2 | 3;
  /** 0 is the primary display; extra screens are 1-3. */
  screen?: number;
};
export type BashResult = {
  output: string;
  error: string | null;
  exit_code: string | number | null;
};
export type ScreenInfo = {
  number: number;
  resolution: string;
  primary: boolean;
};
export type AppEntry = {
  id: string;
  name: string;
  category: string;
  description: string;
  launchable: boolean;
  removable: boolean;
  requires: string[];
  install: {
    id: string;
    status: string;
    error: string | null;
    log: string;
  } | null;
};
export type AutomationBody = {
  name: string;
  trigger:
    | { kind: "schedule"; cron: string; timezone?: string }
    | { kind: "interval"; every_minutes: number }
    | { kind: "webhook" }
    | { kind: "file"; path: string }
    | { kind: "process"; process: string };
  action:
    | { kind: "command"; command: string }
    | { kind: "agent_task"; prompt: string }
    | { kind: "start" }
    | { kind: "stop" };
  enabled?: boolean;
  start_if_stopped?: boolean;
  timeout_minutes?: number;
};
export type TemplateSpec = {
  description?: string;
  apps?: string[];
  packages?: string[];
  files?: { path: string; content: string; mode?: string }[];
  run?: string[];
  startup?: string[];
  env?: Record<string, string>;
  requires_secrets?: string[];
  cpu?: 1 | 2;
  memory_gib?: 2 | 4;
  storage_gib?: 20 | 50 | 100;
  resolution?: "1280x720" | "1440x900" | "1920x1080";
  idle_timeout_minutes?: number;
};
export type Direction = "up" | "down" | "left" | "right";

export class CubicleError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function toBase64(bytes: Uint8Array) {
  if (typeof Buffer !== "undefined")
    return Buffer.from(bytes).toString("base64");
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

function fromBase64(text: string): Uint8Array {
  if (typeof Buffer !== "undefined")
    return new Uint8Array(Buffer.from(text, "base64"));
  return Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
}

export type CubicleOptions = {
  baseUrl: string;
  apiKey: string;
  fetch?: typeof fetch;
};

export class Cubicle {
  private base: string;
  private options: CubicleOptions;
  // Plain field assignments: Node's strip-only TypeScript mode rejects parameter properties.
  constructor(options: CubicleOptions) {
    this.options = options;
    this.base = options.baseUrl.replace(/\/+$/, "");
  }

  async request<T = any>(
    method: string,
    path: string,
    body?: unknown,
    idempotencyKey?: string,
  ): Promise<T> {
    const doFetch = this.options.fetch || fetch;
    const res = await doFetch(this.base + "/v1" + path, {
      method,
      headers: {
        Authorization: "Bearer " + this.options.apiKey,
        "Content-Type": "application/json",
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const detail =
        data && typeof data.detail === "string"
          ? data.detail
          : `HTTP ${res.status}`;
      throw new CubicleError(res.status, detail);
    }
    return data as T;
  }

  workspaces() {
    return this.request<Workspace[]>("GET", "/workspaces");
  }
  computers(workspaceId: string) {
    return this.request<ComputerInfo[]>(
      "GET",
      `/workspaces/${workspaceId}/computers`,
    );
  }
  computer(id: string) {
    return this.request<ComputerInfo>("GET", `/computers/${id}`);
  }
  /** Creates a stopped computer. Pass the same idempotency key when retrying. */
  create(
    workspaceId: string,
    options: CreateOptions,
    idempotencyKey = crypto.randomUUID(),
  ) {
    return this.request<ComputerInfo>(
      "POST",
      `/workspaces/${workspaceId}/computers`,
      options,
      idempotencyKey,
    );
  }
  start(id: string) {
    return this.request<ComputerInfo>(
      "POST",
      `/computers/${id}/actions/start`,
      undefined,
      crypto.randomUUID(),
    );
  }
  stop(id: string) {
    return this.request<ComputerInfo>(
      "POST",
      `/computers/${id}/actions/stop`,
      undefined,
      crypto.randomUUID(),
    );
  }
  rename(id: string, name: string) {
    return this.request<ComputerInfo>("PATCH", `/computers/${id}`, { name });
  }
  /** Deletion erases the home directory; the current name must be repeated to confirm. */
  delete(id: string, confirmName: string) {
    return this.request(
      "DELETE",
      `/computers/${id}?confirm=${encodeURIComponent(confirmName)}`,
      undefined,
      crypto.randomUUID(),
    );
  }
  /** Polls until the computer reaches one of the statuses (default: running) or the timeout passes. */
  async waitFor(
    id: string,
    statuses: string[] = ["running"],
    timeoutMs = 180_000,
    intervalMs = 2_000,
  ) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const c = await this.computer(id);
      if (statuses.includes(c.status)) return c;
      if (c.status === "failed" || c.status === "copy_failed")
        throw new CubicleError(409, c.error || c.status);
      if (Date.now() > deadline)
        throw new CubicleError(
          408,
          `Timed out waiting for ${statuses.join("/")}`,
        );
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }

  screenshot(id: string, screen = 0) {
    return this.request<Screenshot>(
      "POST",
      `/computers/${id}/screenshot?screen=${screen}`,
    );
  }
  async screenshotBytes(id: string, screen = 0) {
    return fromBase64((await this.screenshot(id, screen)).image);
  }
  click(id: string, x: number, y: number, options: ClickOptions = {}) {
    return this.request("POST", `/computers/${id}/click`, { x, y, ...options });
  }
  doubleClick(id: string, x: number, y: number) {
    return this.click(id, x, y, { count: 2 });
  }
  rightClick(id: string, x: number, y: number) {
    return this.click(id, x, y, { button: "right" });
  }
  drag(id: string, from: [number, number], to: [number, number], screen = 0) {
    return this.request("POST", `/computers/${id}/drag`, { from, to, screen });
  }
  scroll(
    id: string,
    x: number,
    y: number,
    direction: Direction = "down",
    amount = 3,
    screen = 0,
  ) {
    return this.request("POST", `/computers/${id}/scroll`, {
      x,
      y,
      direction,
      amount,
      screen,
    });
  }
  type(id: string, text: string, screen = 0) {
    return this.request("POST", `/computers/${id}/type`, { text, screen });
  }
  /** xdotool key syntax, e.g. "Return", "ctrl+l", "alt+F4". */
  key(id: string, key: string, screen = 0) {
    return this.request("POST", `/computers/${id}/key`, { key, screen });
  }
  /** Output is returned even when the command fails; check exit_code. */
  bash(id: string, command: string) {
    return this.request<BashResult>("POST", `/computers/${id}/bash`, {
      command,
    });
  }
  wait(id: string, seconds = 1, screen = 0) {
    return this.request("POST", `/computers/${id}/wait`, { seconds, screen });
  }

  screens(id: string) {
    return this.request<ScreenInfo[]>("GET", `/computers/${id}/screens`);
  }
  addScreen(id: string, resolution = "1440x900") {
    return this.request<ScreenInfo & { live: boolean }>(
      "POST",
      `/computers/${id}/screens`,
      { resolution },
    );
  }
  removeScreen(id: string, screen: number) {
    return this.request("DELETE", `/computers/${id}/screens/${screen}`);
  }

  appCatalog() {
    return this.request<Omit<AppEntry, "install">[]>("GET", "/apps");
  }
  apps(id: string) {
    return this.request<AppEntry[]>("GET", `/computers/${id}/apps`);
  }
  installApp(id: string, appId: string) {
    return this.request("POST", `/computers/${id}/apps/${appId}/install`);
  }
  removeApp(id: string, appId: string) {
    return this.request("POST", `/computers/${id}/apps/${appId}/remove`);
  }
  launchApp(id: string, appId: string, screen = 0) {
    return this.request(
      "POST",
      `/computers/${id}/apps/${appId}/launch?screen=${screen}`,
    );
  }

  automations(id: string) {
    return this.request<any[]>("GET", `/computers/${id}/automations`);
  }
  /** Webhook automations return webhook_token once; store it. */
  createAutomation(id: string, body: AutomationBody) {
    return this.request<any>("POST", `/computers/${id}/automations`, body);
  }
  runAutomation(automationId: string) {
    return this.request<any>("POST", `/automations/${automationId}/run`);
  }
  automationRuns(automationId: string) {
    return this.request<any[]>("GET", `/automations/${automationId}/runs`);
  }
  setAutomationEnabled(automationId: string, enabled: boolean) {
    return this.request<any>("PATCH", `/automations/${automationId}`, {
      enabled,
    });
  }
  deleteAutomation(automationId: string) {
    return this.request("DELETE", `/automations/${automationId}`);
  }

  templateStarters() {
    return this.request<any[]>("GET", "/template-starters");
  }
  templateDefinitions(workspaceId: string) {
    return this.request<any[]>(
      "GET",
      `/workspaces/${workspaceId}/template-definitions`,
    );
  }
  /** Identical specs return the existing version; changed specs build a new one. */
  publishTemplate(
    workspaceId: string,
    name: string,
    spec: TemplateSpec,
    idempotencyKey = crypto.randomUUID(),
  ) {
    return this.request<{ template: any; built: boolean }>(
      "POST",
      `/workspaces/${workspaceId}/template-definitions`,
      { name, spec },
      idempotencyKey,
    );
  }
  template(templateId: string) {
    return this.request<any>("GET", `/templates/${templateId}`);
  }
  createFromTemplate(
    templateId: string,
    options: Partial<CreateOptions> & { name: string },
    idempotencyKey = crypto.randomUUID(),
  ) {
    return this.request<{ id: string; target_id: string; status: string }>(
      "POST",
      `/templates/${templateId}/computers`,
      options,
      idempotencyKey,
    );
  }

  fleet(
    workspaceId: string,
    filters: { q?: string; status?: string; label?: string } = {},
  ) {
    const params = new URLSearchParams(filters as Record<string, string>);
    return this.request<{ summary: any; computers: any[] }>(
      "GET",
      `/workspaces/${workspaceId}/fleet?${params}`,
    );
  }
  setLabels(id: string, labels: string[]) {
    return this.request<{ labels: string[] }>(
      "PUT",
      `/computers/${id}/labels`,
      { labels },
    );
  }
  bulk(
    workspaceId: string,
    ids: string[],
    action: "start" | "stop" | "add_label" | "remove_label",
    label?: string,
  ) {
    return this.request<{
      succeeded: number;
      results: { id: string; ok: boolean; error?: string }[];
    }>("POST", `/workspaces/${workspaceId}/computers/bulk`, {
      ids,
      action,
      ...(label ? { label } : {}),
    });
  }
  move(id: string, workspaceId: string) {
    return this.request("POST", `/computers/${id}/move`, {
      workspace_id: workspaceId,
    });
  }

  files(id: string, path = "") {
    return this.request<FileEntry[]>(
      "GET",
      `/computers/${id}/files?path=${encodeURIComponent(path)}`,
    );
  }
  upload(id: string, path: string, bytes: Uint8Array) {
    return this.request<{ name: string; size: number }>(
      "POST",
      `/computers/${id}/upload`,
      {
        path,
        data: toBase64(bytes),
      },
    );
  }
  async download(id: string, path: string) {
    const r = await this.request<{ name: string; data: string }>(
      "GET",
      `/computers/${id}/download?path=${encodeURIComponent(path)}`,
    );
    return { name: r.name, bytes: fromBase64(r.data) };
  }
  deleteFile(id: string, path: string) {
    return this.request("POST", `/computers/${id}/delete-file`, { path });
  }

  /** Built-in Claude agent task (needs the workspace's Anthropic key and the manage scope). */
  submitTask(id: string, prompt: string) {
    return this.request<{ id: string; status: string }>(
      "POST",
      `/computers/${id}/runs`,
      { prompt },
      crypto.randomUUID(),
    );
  }
  runs(id: string) {
    return this.request<
      { id: string; prompt: string; status: string; steps: number }[]
    >("GET", `/computers/${id}/runs`);
  }
  events(id: string, after = 0) {
    return this.request<{ id: number; kind: string; text: string }[]>(
      "GET",
      `/computers/${id}/events?after=${after}`,
    );
  }
}
