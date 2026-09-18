"use client";
import { useCallback, useEffect, useState } from "react";
import { CalendarClock, Check } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Plan = {
  id: string;
  name: string;
  description: string;
  period_days: number;
  running_computers: number;
  saved_computers: number;
  max_cpu: number;
  max_memory_gib: number;
  max_storage_gib: number;
  gpu: boolean;
  price_usdc: number | null;
  for_sale: boolean;
  free: boolean;
  price_source: "platform" | "credits" | "unavailable";
};
type HourlyRate = {
  tier: string;
  sku: string;
  price_usdc: number | null;
  free: boolean;
};
type Catalog = {
  plans: Plan[];
  billing: "platform" | "credits";
  hourly?: HourlyRate[] | null;
  pay_as_you_go?: { minute_micro_usdc: number; hour_usdc: number };
  renewal: string;
};
type PassInfo = {
  plan_name: string;
  starts_at: string;
  expires_at: string;
  status?: string;
  pay_url?: string | null;
  includes: Record<string, number | boolean | null>;
};

function priceLabel(p: Plan) {
  if (p.price_source === "unavailable") return "PRICE UNAVAILABLE";
  if (p.free) return "FREE";
  return p.price_usdc === null ? "PRICE NOT SET" : `${p.price_usdc} USDC`;
}

function buyLabel(p: Plan) {
  return p.free ? "Start this pass" : "Buy this pass";
}

function buyHint(p: Plan) {
  if (p.price_source === "unavailable")
    return "The payment service is unreachable, so this cannot be bought right now";
  if (p.free) return "No price is set for this plan, so it costs nothing";
  if (!p.for_sale) return "The owner has not set a price for this plan yet";
  return "Pay for this pass";
}

export function Passes({
  workspaceId,
  owner,
}: {
  workspaceId: string;
  owner: boolean;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [current, setCurrent] = useState<PassInfo | null>(null);
  const [pending, setPending] = useState<PassInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    const [c, p] = await Promise.all([
      api<Catalog>("/plans"),
      api<{ active: PassInfo | null }>(`/workspaces/${workspaceId}/pass`),
    ]);
    setCatalog(c);
    setCurrent(p.active);
  }, [workspaceId]);
  useEffect(() => {
    load().catch((e) => setMessage(e.message));
  }, [load]);
  async function buy(plan: Plan) {
    setBusy(true);
    setMessage("");
    try {
      const bought = await api<PassInfo>(
        `/workspaces/${workspaceId}/passes`,
        "POST",
        { plan_id: plan.id },
      );
      if (bought.status === "pending" && bought.pay_url) {
        setPending(bought);
        setMessage(
          `${bought.plan_name} is waiting for payment. It starts the moment the charge is paid.`,
        );
      } else {
        setPending(null);
        setMessage(
          `${bought.plan_name} active until ${new Date(bought.expires_at + "Z").toLocaleString()}.`,
        );
      }
      await load();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const remaining = current
    ? Math.max(
        0,
        Math.round(
          (new Date(current.expires_at + "Z").getTime() - Date.now()) / 3600000,
        ),
      )
    : 0;
  return (
    <article className="settings-card">
      <div className="card-title">
        <CalendarClock size={20} />
        <div>
          <h2>Passes</h2>
          <p>
            Run computers for a fixed period instead of paying per minute. A
            pass never renews itself: buy again before it ends to extend it.
          </p>
        </div>
        {current && <span className="tag">{remaining} H LEFT</span>}
      </div>
      {current && (
        <div className="pass-active">
          <Check size={14} />
          <span>
            <strong>{current.plan_name}</strong> until{" "}
            {new Date(current.expires_at + "Z").toLocaleString()} ·{" "}
            {String(current.includes.running_computers)} running ·{" "}
            {String(current.includes.saved_computers)} saved · up to{" "}
            {String(current.includes.max_storage_gib)} GiB disks
          </span>
        </div>
      )}
      {pending?.pay_url && (
        <div className="pass-active pending">
          <span>
            <strong>{pending.plan_name}</strong> is waiting for payment.
          </span>
          <a href={pending.pay_url} target="_blank" rel="noreferrer">
            Open the payment sheet
          </a>
        </div>
      )}
      <div className="apps-grid">
        {catalog?.plans.map((p) => (
          <article className="app-card" key={p.id}>
            <div className="app-card-head">
              <strong>{p.name}</strong>
              <span className="tag">{priceLabel(p)}</span>
            </div>
            <p>{p.description}</p>
            <p className="field-note">
              {p.running_computers} running · {p.saved_computers} saved · up to{" "}
              {p.max_cpu} vCPU, {p.max_memory_gib} GiB RAM, {p.max_storage_gib}{" "}
              GiB disk
              {p.gpu ? " · GPU allowed" : ""}
            </p>
            <div className="app-card-actions">
              <Button
                variant="ghost"
                disabled={!owner || busy || !p.for_sale}
                title={buyHint(p)}
                onClick={() => buy(p)}
              >
                {current ? "Extend with this pass" : buyLabel(p)}
              </Button>
            </div>
          </article>
        ))}
      </div>
      {message && (
        <p role="status" className="field-note">
          {message}
        </p>
      )}
      {catalog?.billing === "platform" ? (
        <div className="field-note">
          <p>
            Without a pass, runtime is charged by the hour for each running
            computer, at the rate for its size:
          </p>
          {catalog.hourly ? (
            <ul className="rate-list">
              {catalog.hourly.map((r) => (
                <li key={r.sku}>
                  <strong>{r.tier}</strong>{" "}
                  {r.free
                    ? "free (no price set)"
                    : `${r.price_usdc} USDC / hour`}
                </li>
              ))}
            </ul>
          ) : (
            <p>Rates are unavailable right now, so nothing is quoted here.</p>
          )}
          <p>
            Computers larger than a pass includes stay on hourly billing even
            while the pass is active. {catalog.renewal}
          </p>
        </div>
      ) : (
        <p className="field-note">
          Without a pass, runtime is metered per minute from your credits
          {catalog?.pay_as_you_go
            ? ` (${catalog.pay_as_you_go.minute_micro_usdc} micro-USDC per minute, about ${catalog.pay_as_you_go.hour_usdc} USDC per hour)`
            : ""}
          . Computers larger than a pass includes stay on per-minute billing
          even while the pass is active. {catalog?.renewal}
        </p>
      )}
    </article>
  );
}
