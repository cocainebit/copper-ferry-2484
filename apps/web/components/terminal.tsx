"use client";
import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import { api } from "@/lib/api";

function socketOrigin() {
  return (
    process.env.NEXT_PUBLIC_WS_URL ||
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api`
  );
}

/**
 * Interactive shell over the API's PTY relay. Mounted only while the viewer holds control;
 * the parent falls back to the one-shot command form when the relay is unavailable.
 */
export function TerminalPanel({
  computerId,
  onUnavailable,
}: {
  computerId: string;
  onUnavailable: (reason: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState("Connecting");
  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | undefined;
    let dispose: (() => void) | undefined;
    (async () => {
      try {
        const [{ Terminal }, { FitAddon }, ticket] = await Promise.all([
          import("@xterm/xterm"),
          import("@xterm/addon-fit"),
          api<{ ticket: string }>(
            `/computers/${computerId}/terminal-ticket`,
            "POST",
          ),
        ]);
        if (disposed || !host.current) return;
        const term = new Terminal({
          cursorBlink: true,
          fontSize: 12,
          fontFamily:
            "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          theme: { background: "#0b0b0d", foreground: "#c9d1c9" },
          scrollback: 5000,
        });
        const fit = new FitAddon();
        term.loadAddon(fit);
        term.open(host.current);
        fit.fit();
        socket = new WebSocket(
          `${socketOrigin()}/v1/computers/${computerId}/pty?ticket=${encodeURIComponent(ticket.ticket)}`,
        );
        socket.binaryType = "arraybuffer";
        const encoder = new TextEncoder();
        let received = false;
        socket.onopen = () => {
          setState("Connected");
          socket?.send(JSON.stringify({ resize: [term.cols, term.rows] }));
          term.focus();
        };
        socket.onmessage = (event) => {
          if (typeof event.data === "string") {
            try {
              const control = JSON.parse(event.data);
              if ("exit" in control)
                term.write(`\r\n[shell exited with code ${control.exit}]\r\n`);
            } catch {}
            return;
          }
          received = true;
          term.write(new Uint8Array(event.data));
        };
        socket.onclose = () => {
          if (disposed) return;
          setState("Disconnected");
          if (!received)
            onUnavailable(
              "The interactive terminal is not available on this computer yet. Computers created before this update keep the command runner below; recreate the computer to get a full shell.",
            );
        };
        term.onData((data) => {
          if (socket?.readyState === WebSocket.OPEN)
            socket.send(encoder.encode(data));
        });
        const observer = new ResizeObserver(() => {
          fit.fit();
          if (socket?.readyState === WebSocket.OPEN)
            socket.send(JSON.stringify({ resize: [term.cols, term.rows] }));
        });
        observer.observe(host.current);
        dispose = () => {
          observer.disconnect();
          term.dispose();
        };
      } catch (e) {
        if (!disposed) onUnavailable((e as Error).message);
      }
    })();
    return () => {
      disposed = true;
      socket?.close();
      dispose?.();
    };
  }, [computerId, onUnavailable]);
  return (
    <div className="terminal-live">
      <div className="terminal-status">
        <span
          className={"status-dot " + (state === "Connected" ? "green" : "")}
        />
        {state} · administrator shell · Ctrl+Shift+V pastes
      </div>
      <div className="terminal-host" ref={host} />
    </div>
  );
}
