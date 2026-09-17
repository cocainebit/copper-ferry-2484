#!/usr/bin/env node
/**
 * Cubicle MCP server (stdio). Exposes computers as tools for Claude Code, Claude Desktop, Cursor and
 * any other MCP client. Configure with CUBICLE_API_URL and CUBICLE_API_KEY.
 *
 * Screenshots come back as image content so the model can look at the desktop directly.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { Cubicle, CubicleError } from "@cubicle/sdk";

const apiKey = process.env.CUBICLE_API_KEY;
if (!apiKey) {
  console.error("CUBICLE_API_KEY is required");
  process.exit(1);
}
const client = new Cubicle({
  baseUrl: process.env.CUBICLE_API_URL || "http://localhost:8000",
  apiKey,
});

const server = new McpServer({ name: "cubicle", version: "0.1.0" });
const id = z.string().describe("Computer id");

function text(value: unknown) {
  return {
    content: [
      {
        type: "text" as const,
        text:
          typeof value === "string" ? value : JSON.stringify(value, null, 2),
      },
    ],
  };
}

async function guarded<T>(fn: () => Promise<T>) {
  try {
    return await fn();
  } catch (e) {
    const message =
      e instanceof CubicleError
        ? `${e.status}: ${e.message}`
        : String((e as Error).message || e);
    return {
      content: [{ type: "text" as const, text: "Error: " + message }],
      isError: true,
    };
  }
}

server.registerTool(
  "list_computers",
  {
    description:
      "List the computers in the workspace this key can see, with status and resources.",
    inputSchema: {},
  },
  async () =>
    guarded(async () => {
      const workspaces = await client.workspaces();
      const all = await Promise.all(
        workspaces.map((w) => client.computers(w.id)),
      );
      return text(all.flat());
    }),
);

server.registerTool(
  "get_computer",
  {
    description: "Show one computer's status, controller and resources.",
    inputSchema: { id },
  },
  async ({ id }) => guarded(async () => text(await client.computer(id))),
);

server.registerTool(
  "start_computer",
  {
    description:
      "Start a stopped computer and wait until it is running (up to 3 minutes). Needs the manage scope.",
    inputSchema: { id },
  },
  async ({ id }) =>
    guarded(async () => {
      await client.start(id);
      return text(await client.waitFor(id));
    }),
);

server.registerTool(
  "stop_computer",
  {
    description:
      "Stop a computer. Files and installed software are preserved. Needs the manage scope.",
    inputSchema: { id },
  },
  async ({ id }) => guarded(async () => text(await client.stop(id))),
);

server.registerTool(
  "screenshot",
  {
    description:
      "Take a screenshot of the live desktop. Coordinates for click/drag/scroll use this image's pixels.",
    inputSchema: { id },
  },
  async ({ id }) =>
    guarded(async () => {
      const shot = await client.screenshot(id);
      return {
        content: [
          { type: "image" as const, data: shot.image, mimeType: "image/png" },
          { type: "text" as const, text: `${shot.width}x${shot.height}` },
        ],
      };
    }),
);

server.registerTool(
  "click",
  {
    description:
      "Click at pixel coordinates. button: left (default), right or middle; count: 1, 2 (double) or 3.",
    inputSchema: {
      id,
      x: z.number().int().min(0),
      y: z.number().int().min(0),
      button: z.enum(["left", "right", "middle"]).optional(),
      count: z.union([z.literal(1), z.literal(2), z.literal(3)]).optional(),
    },
  },
  async ({ id, x, y, button, count }) =>
    guarded(async () => text(await client.click(id, x, y, { button, count }))),
);

server.registerTool(
  "type_text",
  {
    description: "Type text into the focused window (Unicode safe).",
    inputSchema: { id, text: z.string().min(1).max(10000) },
  },
  async ({ id, text: value }) =>
    guarded(async () => text(await client.type(id, value))),
);

server.registerTool(
  "press_key",
  {
    description:
      "Press a key or chord in xdotool syntax: Return, Tab, Escape, ctrl+l, ctrl+shift+t, alt+F4.",
    inputSchema: { id, key: z.string().regex(/^[A-Za-z0-9_+\-]+$/) },
  },
  async ({ id, key }) => guarded(async () => text(await client.key(id, key))),
);

server.registerTool(
  "scroll",
  {
    description:
      "Scroll at a position. direction: up, down, left, right; amount: wheel ticks (default 3).",
    inputSchema: {
      id,
      x: z.number().int().min(0),
      y: z.number().int().min(0),
      direction: z.enum(["up", "down", "left", "right"]).optional(),
      amount: z.number().int().min(1).max(100).optional(),
    },
  },
  async ({ id, x, y, direction, amount }) =>
    guarded(async () => text(await client.scroll(id, x, y, direction, amount))),
);

server.registerTool(
  "drag",
  {
    description: "Drag with the left button from one point to another.",
    inputSchema: {
      id,
      x1: z.number().int(),
      y1: z.number().int(),
      x2: z.number().int(),
      y2: z.number().int(),
    },
  },
  async ({ id, x1, y1, x2, y2 }) =>
    guarded(async () => text(await client.drag(id, [x1, y1], [x2, y2]))),
);

server.registerTool(
  "bash",
  {
    description:
      "Run a shell command as administrator inside the computer (45 second limit). Returns stdout and stderr.",
    inputSchema: { id, command: z.string().min(1).max(8000) },
  },
  async ({ id, command }) =>
    guarded(async () => {
      const r = await client.bash(id, command);
      return {
        content: [
          {
            type: "text" as const,
            text: r.error ? `${r.output}\n[error] ${r.error}` : r.output,
          },
        ],
        isError: !!r.error,
      };
    }),
);

server.registerTool(
  "wait",
  {
    description: "Pause up to 10 seconds, for pages or apps to settle.",
    inputSchema: { id, seconds: z.number().min(0).max(10).optional() },
  },
  async ({ id, seconds }) =>
    guarded(async () => text(await client.wait(id, seconds))),
);

server.registerTool(
  "list_files",
  {
    description: "List files in the computer's Home or a folder under it.",
    inputSchema: { id, path: z.string().optional() },
  },
  async ({ id, path }) =>
    guarded(async () => text(await client.files(id, path || ""))),
);

server.registerTool(
  "read_file",
  {
    description: "Read a UTF-8 text file from Home (20 MB limit).",
    inputSchema: { id, path: z.string().min(1) },
  },
  async ({ id, path }) =>
    guarded(async () => {
      const file = await client.download(id, path);
      return text(new TextDecoder().decode(file.bytes));
    }),
);

server.registerTool(
  "write_file",
  {
    description: "Write a UTF-8 text file into Home, creating parent folders.",
    inputSchema: { id, path: z.string().min(1), content: z.string() },
  },
  async ({ id, path, content }) =>
    guarded(async () =>
      text(await client.upload(id, path, new TextEncoder().encode(content))),
    ),
);

await server.connect(new StdioServerTransport());
