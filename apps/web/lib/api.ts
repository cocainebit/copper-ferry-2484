import { createClient } from "@supabase/supabase-js";
import { platformToken } from "@/lib/platform-auth";
export const supabase =
  process.env.NEXT_PUBLIC_SUPABASE_URL &&
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
    ? createClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL,
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
      )
    : null;
export async function token() {
  if (
    process.env.NEXT_PUBLIC_DEV_MODE === "true" &&
    typeof window !== "undefined" &&
    sessionStorage.getItem("use-local-workspace") === "true"
  )
    return "local-development-only";
  const platform = await platformToken();
  if (platform) return platform;
  if (supabase)
    return (await supabase.auth.getSession()).data.session?.access_token || "";
  return process.env.NEXT_PUBLIC_DEV_MODE === "true"
    ? "local-development-only"
    : "";
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const res = await fetch("/api/v1" + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + (await token()),
      ...(["POST", "DELETE"].includes(method)
        ? { "Idempotency-Key": crypto.randomUUID() }
        : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const data = await res.json();
  if (!res.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Request failed. Please try again.",
    );
  return data;
}
export type Computer = {
  id: string;
  name: string;
  status: string;
  controller: string;
  error: string | null;
  workspace_id: string;
  cpu?: number;
  memory_gib?: number;
  storage_gib?: number;
  resolution?: string;
  os?: string;
  gpu?: number;
};
export type Workspace = {
  id: string;
  name: string;
  role: string;
  credits: number;
  subscription: string;
  has_key: boolean;
};
export type Run = {
  id: string;
  prompt: string;
  status: string;
  approval?: { action: string };
  steps: number;
};
export type Activity = { id: number; kind: string; text: string };
