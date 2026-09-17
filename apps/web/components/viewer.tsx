"use client";
import { useEffect, useRef, useState } from "react";
import { Monitor, Maximize2, RefreshCw } from "lucide-react";
import { api, type Computer } from "@/lib/api";
import { Button } from "@/components/ui/button";
export function Viewer({
  computer,
  onStart,
}: {
  computer: Computer;
  onStart: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("Connecting");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (computer.status !== "running") return;
    let disposed = false;
    let rfb: any;
    setStatus("Connecting");
    (async () => {
      try {
        const ticket = await api(
          `/computers/${computer.id}/viewer-ticket`,
          "POST",
        );
        const { default: RFB } = await import("@novnc/novnc");
        if (disposed || !host.current) return;
        const origin =
          process.env.NEXT_PUBLIC_WS_URL ||
          `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api`;
        rfb = new RFB(
          host.current,
          `${origin}/v1/computers/${computer.id}/desktop?ticket=${encodeURIComponent(ticket.ticket)}`,
          { credentials: { password: ticket.password } },
        );
        rfb.scaleViewport = true;
        rfb.resizeSession = false;
        rfb.viewOnly = !ticket.control;
        rfb.addEventListener("connect", () => setStatus("Connected"));
        rfb.addEventListener("disconnect", () => setStatus("Disconnected"));
        rfb.addEventListener("securityfailure", () =>
          setStatus("Connection rejected"),
        );
      } catch (e) {
        setStatus((e as Error).message);
      }
    })();
    return () => {
      disposed = true;
      rfb?.disconnect();
    };
  }, [computer.id, computer.status, computer.controller, attempt]);
  return (
    <div className="viewer-wrap">
      <div className="viewer-toolbar">
        <span>
          <span
            className={
              "status-dot " + (computer.status === "running" ? "green" : "")
            }
          />
          {computer.status === "running" ? status : computer.status}
        </span>
        <div>
          <button
            title="Reconnect desktop"
            aria-label="Reconnect desktop"
            onClick={() => setAttempt((x) => x + 1)}
          >
            <RefreshCw size={14} />
          </button>
          <button
            title="Fullscreen"
            aria-label="Fullscreen"
            onClick={() => host.current?.parentElement?.requestFullscreen()}
          >
            <Maximize2 size={14} />
          </button>
        </div>
      </div>
      <div className="viewer-stage">
        <div className="vnc-host" ref={host} />
        {computer.status !== "running" ? (
          <div className="desktop-empty">
            <div className="monitor-icon">
              <Monitor size={34} strokeWidth={1} />
            </div>
            <h2>
              {computer.status === "starting"
                ? "Making room for your ideas…"
                : computer.status === "copying"
                  ? "Preparing your template…"
                  : computer.status === "copy_failed"
                    ? "Your computer could not be copied."
                    : "Your computer is taking a breather."}
            </h2>
            <p>
              {computer.error ||
                (computer.status === "copying"
                  ? "Your environment is being copied. Start the computer once it is ready."
                  : "Your files and browser profile will be here when you return.")}
            </p>
            {["stopped", "failed"].includes(computer.status) && (
              <Button onClick={onStart}>Start computer</Button>
            )}
          </div>
        ) : (
          status !== "Connected" && (
            <div className="connection-label">
              {status}
              {status !== "Connecting" && (
                <button onClick={() => setAttempt((x) => x + 1)}>
                  Reconnect
                </button>
              )}
            </div>
          )
        )}
      </div>
    </div>
  );
}
