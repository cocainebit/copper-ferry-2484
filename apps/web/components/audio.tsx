"use client";
import { useEffect, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Opt-in desktop sound. Streams 16-bit mono PCM from the computer's speaker sink and schedules it on
 * an AudioContext with a small buffer, so nothing is captured or played until the viewer asks.
 */
export function AudioToggle({ computerId }: { computerId: string }) {
  const [on, setOn] = useState(false);
  const [state, setState] = useState("");
  const socket = useRef<WebSocket | null>(null);
  const context = useRef<AudioContext | null>(null);
  useEffect(() => {
    if (!on) return;
    let disposed = false;
    let nextTime = 0;
    let rate = 24000;
    (async () => {
      try {
        const ticket = await api<{ ticket: string }>(
          `/computers/${computerId}/audio-ticket`,
          "POST",
        );
        if (disposed) return;
        const ctx = new AudioContext();
        context.current = ctx;
        const origin =
          process.env.NEXT_PUBLIC_WS_URL ||
          `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api`;
        const ws = new WebSocket(
          `${origin}/v1/computers/${computerId}/audio?ticket=${encodeURIComponent(ticket.ticket)}`,
        );
        ws.binaryType = "arraybuffer";
        socket.current = ws;
        setState("Connecting");
        ws.onmessage = (event) => {
          if (typeof event.data === "string") {
            try {
              rate = JSON.parse(event.data).rate || rate;
              setState("Listening");
            } catch {}
            return;
          }
          const pcm = new Int16Array(event.data);
          const buffer = ctx.createBuffer(1, pcm.length, rate);
          const channel = buffer.getChannelData(0);
          for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
          const source = ctx.createBufferSource();
          source.buffer = buffer;
          source.connect(ctx.destination);
          // Keep roughly 120 ms of headroom; resync after gaps instead of drifting.
          if (nextTime < ctx.currentTime + 0.05)
            nextTime = ctx.currentTime + 0.12;
          source.start(nextTime);
          nextTime += buffer.duration;
        };
        ws.onclose = () => {
          if (!disposed)
            setState(
              "Sound unavailable on this computer (restart it after updates)",
            );
        };
      } catch (e) {
        if (!disposed) setState((e as Error).message);
      }
    })();
    return () => {
      disposed = true;
      socket.current?.close();
      context.current?.close();
      socket.current = null;
      context.current = null;
      setState("");
    };
  }, [on, computerId]);
  return (
    <button
      title={on ? state || "Mute desktop sound" : "Play desktop sound"}
      aria-label={on ? "Mute desktop sound" : "Play desktop sound"}
      aria-pressed={on}
      onClick={() => setOn((x) => !x)}
    >
      {on ? <Volume2 size={14} /> : <VolumeX size={14} />}
    </button>
  );
}
