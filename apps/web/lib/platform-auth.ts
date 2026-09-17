// OAuth 2.1 authorization code + PKCE against the Instance platform.
// This runs in the browser as a public client, so there is no client secret here.
const PLATFORM_URL = (process.env.NEXT_PUBLIC_PLATFORM_URL || "").replace(
  /\/+$/,
  "",
);
const CLIENT_ID = process.env.NEXT_PUBLIC_PLATFORM_CLIENT_ID || "";
const ISSUER = PLATFORM_URL ? PLATFORM_URL + "/api/auth" : "";
const AUTHORIZE_ENDPOINT = ISSUER + "/oauth2/authorize";
const TOKEN_ENDPOINT = ISSUER + "/oauth2/token";
const SCOPE = "openid profile email offline_access";
const SESSION_KEY = "platform-session";
const VERIFIER_KEY = "platform-pkce-verifier";
const STATE_KEY = "platform-auth-state";
// Refresh this long before the access token actually expires.
const REFRESH_WINDOW_MS = 60_000;
// Used only when the token response omits expires_in, so we re-check often.
const DEFAULT_LIFETIME_MS = 300_000;
export type PlatformSession = {
  access_token: string;
  refresh_token: string;
  expires_at: number;
};
type Store = "local" | "session";
function storage(kind: Store): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}
function read(kind: Store, key: string): string {
  try {
    return storage(kind)?.getItem(key) || "";
  } catch {
    return "";
  }
}
function write(kind: Store, key: string, value: string) {
  try {
    storage(kind)?.setItem(key, value);
  } catch {
    // Storage can be blocked or full. Sign-in still works for this page load.
  }
}
function remove(kind: Store, key: string) {
  try {
    storage(kind)?.removeItem(key);
  } catch {
    // Nothing to do if storage is unavailable.
  }
}
function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
function randomToken(bytes: number): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return base64url(buffer);
}
async function codeChallenge(verifier: string): Promise<string> {
  if (typeof crypto === "undefined" || !crypto.subtle)
    throw new Error(
      "This browser cannot create a secure sign-in request. Open the app over localhost or HTTPS.",
    );
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return base64url(new Uint8Array(digest));
}
export function platformConfigured(): boolean {
  return Boolean(PLATFORM_URL && CLIENT_ID);
}
export function redirectUri(): string {
  const configured = (
    process.env.NEXT_PUBLIC_PLATFORM_REDIRECT_URI || ""
  ).trim();
  if (configured) return configured;
  if (typeof window === "undefined") return "";
  return window.location.origin + "/auth/callback";
}
// The platform only accepts its exact registered callback. In local development
// that callback is on 127.0.0.1, so a page opened on localhost would be turned
// away there, and the verifier written here would not be readable on the other
// origin anyway. Fail early with something the reader can act on.
function checkOrigin() {
  if (process.env.NEXT_PUBLIC_PLATFORM_REDIRECT_URI) return;
  let host = "";
  try {
    host = new URL(PLATFORM_URL).hostname;
  } catch {
    return;
  }
  const local = host === "127.0.0.1" || host === "localhost" || host === "::1";
  if (!local || window.location.hostname === host) return;
  const port = window.location.port ? ":" + window.location.port : "";
  throw new Error(
    "Open the dashboard at http://" +
      host +
      port +
      " to sign in with Instance.",
  );
}
function loadSession(): PlatformSession | null {
  const raw = read("local", SESSION_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PlatformSession>;
    if (!parsed || typeof parsed.access_token !== "string") return null;
    if (!parsed.access_token) return null;
    return {
      access_token: parsed.access_token,
      refresh_token:
        typeof parsed.refresh_token === "string" ? parsed.refresh_token : "",
      expires_at:
        typeof parsed.expires_at === "number" && isFinite(parsed.expires_at)
          ? parsed.expires_at
          : 0,
    };
  } catch {
    return null;
  }
}
function saveSession(session: PlatformSession) {
  write("local", SESSION_KEY, JSON.stringify(session));
}
type TokenResponse = {
  access_token?: unknown;
  refresh_token?: unknown;
  expires_in?: unknown;
  error?: unknown;
  error_description?: unknown;
};
async function requestTokens(
  form: URLSearchParams,
  fallbackRefreshToken = "",
): Promise<PlatformSession> {
  let res: Response;
  try {
    res = await fetch(TOKEN_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json",
      },
      body: form.toString(),
    });
  } catch {
    // fetch only reports a bare TypeError here, so name both likely causes.
    throw new Error(
      "Could not reach the Instance platform at " +
        PLATFORM_URL +
        ". Check that it is running and that it allows browser requests from " +
        (typeof window === "undefined" ? "this app" : window.location.origin) +
        ".",
    );
  }
  let data: TokenResponse = {};
  try {
    data = (await res.json()) as TokenResponse;
  } catch {
    data = {};
  }
  if (!res.ok) {
    const detail =
      (typeof data.error_description === "string" && data.error_description) ||
      (typeof data.error === "string" && data.error) ||
      "HTTP " + res.status;
    throw new Error("The platform rejected the sign-in: " + detail);
  }
  if (typeof data.access_token !== "string" || !data.access_token)
    throw new Error("The platform did not return an access token.");
  const lifetime =
    typeof data.expires_in === "number" && data.expires_in > 0
      ? data.expires_in * 1000
      : DEFAULT_LIFETIME_MS;
  return {
    access_token: data.access_token,
    refresh_token:
      typeof data.refresh_token === "string" && data.refresh_token
        ? data.refresh_token
        : fallbackRefreshToken,
    expires_at: Date.now() + lifetime,
  };
}
export async function startSignIn(): Promise<void> {
  if (!platformConfigured())
    throw new Error("Instance sign-in is not configured yet.");
  if (typeof window === "undefined") return;
  checkOrigin();
  const target = redirectUri();
  if (!target) throw new Error("Instance sign-in is not configured yet.");
  const verifier = randomToken(64);
  const state = randomToken(32);
  const challenge = await codeChallenge(verifier);
  write("session", VERIFIER_KEY, verifier);
  write("session", STATE_KEY, state);
  remove("session", "use-local-workspace");
  const params = new URLSearchParams({
    response_type: "code",
    client_id: CLIENT_ID,
    redirect_uri: target,
    scope: SCOPE,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  window.location.href = AUTHORIZE_ENDPOINT + "?" + params.toString();
}
export async function completeSignIn(
  searchParams: URLSearchParams,
): Promise<PlatformSession> {
  if (!platformConfigured())
    throw new Error("Instance sign-in is not configured yet.");
  const failure = searchParams.get("error");
  if (failure) {
    const description = searchParams.get("error_description");
    throw new Error(
      failure === "access_denied"
        ? "Sign-in was cancelled."
        : "The platform returned an error: " + (description || failure),
    );
  }
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const expectedState = read("session", STATE_KEY);
  if (!code)
    throw new Error("The sign-in response did not include an authorization.");
  if (!expectedState || !state || state !== expectedState)
    throw new Error(
      "This sign-in response does not match the request. Please sign in again.",
    );
  const issuer = searchParams.get("iss");
  if (issuer && issuer.replace(/\/+$/, "") !== ISSUER)
    throw new Error("The sign-in response came from an unexpected issuer.");
  const verifier = read("session", VERIFIER_KEY);
  if (!verifier)
    throw new Error("The sign-in request expired. Please sign in again.");
  const session = await requestTokens(
    new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(),
      client_id: CLIENT_ID,
      code_verifier: verifier,
    }),
  );
  saveSession(session);
  remove("session", VERIFIER_KEY);
  remove("session", STATE_KEY);
  remove("session", "use-local-workspace");
  return session;
}
let refreshing: Promise<string> | null = null;
async function refresh(refreshToken: string): Promise<string> {
  try {
    const session = await requestTokens(
      new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: refreshToken,
        client_id: CLIENT_ID,
      }),
      refreshToken,
    );
    saveSession(session);
    return session.access_token;
  } catch {
    platformSignOut();
    return "";
  }
}
export async function platformToken(): Promise<string> {
  const session = loadSession();
  if (!session) return "";
  if (
    !session.expires_at ||
    session.expires_at - Date.now() > REFRESH_WINDOW_MS
  )
    return session.access_token;
  if (!session.refresh_token) {
    platformSignOut();
    return "";
  }
  if (!refreshing)
    refreshing = refresh(session.refresh_token).finally(() => {
      refreshing = null;
    });
  return refreshing;
}
export function platformSignOut() {
  remove("local", SESSION_KEY);
  remove("session", VERIFIER_KEY);
  remove("session", STATE_KEY);
}
