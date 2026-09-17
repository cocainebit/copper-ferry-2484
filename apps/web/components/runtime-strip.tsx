"use client";
import { useCallback, useEffect, useState } from "react";
import { Clock, ExternalLink } from "lucide-react";
import { api, type Computer } from "@/lib/api";

type Block = {
  status: string;
  pay_url: string | null;
  expires_at: string;
  amount_micro_usdc: number;
};
type Runtime = {
  billing: "platform" | "credits";
  covered_until: string | null;
  covered_by: "pass" | "hour" | null;
  grace_minutes: number;
  next: Block | null;
};

const at = (value: string) => new Date(value + "Z").toLocaleTimeString();

/** Shows who is paying for the running desktop and, when payment is due, where to pay it. */
export function RuntimeStrip({
  computer,
  owner,
}: {
  computer: Computer;
  owner: boolean;
}) {
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setRuntime(await api<Runtime>(`/computers/${computer.id}/runtime`));
  }, [computer.id]);
  useEffect(() => {
    load().catch(() => {});
    const timer = setInterval(() => load().catch(() => {}), 15000);
    return () => clearInterval(timer);
  }, [load]);
  if (!runtime || runtime.billing !== "platform") return null;
  const due =
    runtime.next && runtime.next.status === "open" ? runtime.next : null;
  const minutesLeft = runtime.covered_until
    ? Math.round(
        (new Date(runtime.covered_until + "Z").getTime() - Date.now()) / 60000,
      )
    : 0;
  return (
    <div className={"runtime-strip" + (due ? " due" : "")}>
      <span>
        <Clock size={13} />
        {runtime.covered_until
          ? runtime.covered_by === "pass"
            ? `Covered by your pass until ${new Date(runtime.covered_until + "Z").toLocaleString()}`
            : `Runtime paid until ${at(runtime.covered_until)} (${minutesLeft} min left)`
          : "Runtime is not paid yet"}
      </span>
      {due ? (
        <a href={due.pay_url || "#"} target="_blank" rel="noreferrer">
          Pay {(due.amount_micro_usdc / 1_000_000).toFixed(2)} USDC for the next
          hour <ExternalLink size={12} />
        </a>
      ) : (
        owner && (
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api(`/computers/${computer.id}/runtime/hours`, "POST");
                await load();
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            Buy the next hour
          </button>
        )
      )}
    </div>
  );
}
