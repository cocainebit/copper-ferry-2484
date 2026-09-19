"use client";
import { useCallback, useEffect, useState } from "react";
import { Clock, ExternalLink } from "lucide-react";
import { api, type Computer } from "@/lib/api";

type Pack = {
  id: string;
  hours: number;
  status: string;
  pay_url: string | null;
  amount_micro_usdc: number;
};
type Runtime = {
  billing: "platform" | "credits";
  seconds_left: number;
  cap_hours: number;
  used_this_window_seconds: number;
  window_days: number;
  capped: boolean;
  covered_by_pass: boolean;
  price_micro_usdc_per_hour: number | null;
  free: boolean;
  price_unavailable: boolean;
  due: Pack | null;
};

function duration(seconds: number) {
  if (seconds < 60) return `${seconds} s`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (!hours) return `${minutes} min`;
  return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
}

const usdc = (micro: number) => (micro / 1_000_000).toFixed(2);
// One decimal where it carries information, none where it would only say ".0".
const hoursLabel = (hours: number) => hours.toFixed(1).replace(/\.0$/, "");

/** Paid runtime for one computer: what is left, the month against its cap, and where to pay. */
export function RuntimeStrip({
  computer,
  owner,
}: {
  computer: Computer;
  owner: boolean;
}) {
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const load = useCallback(async () => {
    setRuntime(await api<Runtime>(`/computers/${computer.id}/runtime`));
  }, [computer.id]);
  useEffect(() => {
    load().catch(() => {});
    const timer = setInterval(() => load().catch(() => {}), 15000);
    return () => clearInterval(timer);
  }, [load]);
  if (!runtime || runtime.billing !== "platform") return null;

  const usedHours = runtime.used_this_window_seconds / 3600;
  const capShare = runtime.cap_hours
    ? Math.min(1, usedHours / runtime.cap_hours)
    : 0;
  const metered =
    !runtime.free &&
    !runtime.covered_by_pass &&
    !runtime.capped &&
    !runtime.price_unavailable;
  const due = runtime.due && runtime.due.status === "open" ? runtime.due : null;
  const price = runtime.price_micro_usdc_per_hour;

  async function buy(hours: number) {
    setBusy(true);
    setProblem("");
    try {
      await api(`/computers/${computer.id}/runtime/hours`, "POST", { hours });
      await load();
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  let headline: string;
  if (runtime.price_unavailable)
    headline = "Runtime prices are unavailable right now";
  else if (runtime.free) headline = "Runtime is free on this size";
  else if (runtime.covered_by_pass) headline = "Covered by your pass";
  else if (runtime.capped)
    headline = `Monthly cap reached. Free for the rest of this ${runtime.window_days}-day window`;
  else if (runtime.seconds_left > 0)
    headline = `${duration(runtime.seconds_left)} of paid runtime left`;
  else
    headline =
      computer.status === "starting"
        ? "Waiting for runtime to be paid"
        : "No paid runtime";

  return (
    <div className={"runtime-strip" + (due ? " due" : "")}>
      <span className="runtime-now">
        <Clock size={13} aria-hidden />
        <strong>{headline}</strong>
      </span>
      {runtime.cap_hours > 0 && !runtime.free && !runtime.price_unavailable && (
        <span
          className="runtime-cap"
          title={`Billed by the second. No computer pays for more than ${runtime.cap_hours} h in any ${runtime.window_days} days; past that, the rest of the window is free.`}
        >
          <span
            className="runtime-meter"
            role="meter"
            aria-label="Paid hours this month against the monthly cap"
            aria-valuemin={0}
            aria-valuemax={runtime.cap_hours}
            aria-valuenow={Math.round(usedHours * 10) / 10}
          >
            <span style={{ width: `${capShare * 100}%` }} />
          </span>
          {hoursLabel(usedHours)} of {runtime.cap_hours} h this month
        </span>
      )}
      {due ? (
        <a href={due.pay_url || "#"} target="_blank" rel="noreferrer">
          Pay {usdc(due.amount_micro_usdc)} USDC for {due.hours} h
          <ExternalLink size={12} aria-hidden />
        </a>
      ) : (
        metered &&
        owner && (
          <span
            className="runtime-buy"
            role="group"
            aria-label="Add paid runtime"
          >
            <span className="runtime-buy-label">Add</span>
            {[...new Set([1, 10, runtime.cap_hours])]
              .filter((hours) => hours > 0)
              .map((hours) => (
                <button
                  key={hours}
                  disabled={busy}
                  onClick={() => buy(hours)}
                  title={
                    price
                      ? `${hours} h for ${usdc(price * hours)} USDC. Unused hours stay with this computer.`
                      : `${hours} h`
                  }
                >
                  {hours} h
                </button>
              ))}
          </span>
        )
      )}
      {problem && (
        <span role="alert" className="runtime-problem">
          {problem}
        </span>
      )}
    </div>
  );
}
