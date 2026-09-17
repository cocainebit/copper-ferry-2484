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
};
export type Direction = "up" | "down" | "left" | "right";

export class CubicleError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
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

export class Cubicle {
  private base: string;
  constructor(
    private options: { baseUrl: string; apiKey: string; fetch?: typeof fetch },
  ) {
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

  screenshot(id: string) {
    return this.request<Screenshot>("POST", `/computers/${id}/screenshot`);
  }
  async screenshotBytes(id: string) {
    return fromBase64((await this.screenshot(id)).image);
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
  drag(id: string, from: [number, number], to: [number, number]) {
    return this.request("POST", `/computers/${id}/drag`, { from, to });
  }
  scroll(
    id: string,
    x: number,
    y: number,
    direction: Direction = "down",
    amount = 3,
  ) {
    return this.request("POST", `/computers/${id}/scroll`, {
      x,
      y,
      direction,
      amount,
    });
  }
  type(id: string, text: string) {
    return this.request("POST", `/computers/${id}/type`, { text });
  }
  /** xdotool key syntax, e.g. "Return", "ctrl+l", "alt+F4". */
  key(id: string, key: string) {
    return this.request("POST", `/computers/${id}/key`, { key });
  }
  bash(id: string, command: string) {
    return this.request<{ output: string; error: string | null }>(
      "POST",
      `/computers/${id}/bash`,
      { command },
    );
  }
  wait(id: string, seconds = 1) {
    return this.request("POST", `/computers/${id}/wait`, { seconds });
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
