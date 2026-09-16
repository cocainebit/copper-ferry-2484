/** Shared client for the broader platform. Never submit a browser-supplied balance as proof. */
export type TrialIntent = { id: string; message: string; expires_at: string };
export type PaymentInstructions = {
  chain: string;
  token: string;
  recipient: string;
  amount: "1";
  amount_atomic: string;
  minimum_remaining: "10000";
  expires_at: string;
};
export type TrialEntitlement = {
  id: string;
  service: string;
  expires_at: string;
  credits: number;
};
export class PlatformTrials {
  constructor(
    private baseURL: string,
    private accessToken: () => Promise<string>,
  ) {}
  private async request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(
      this.baseURL.replace(/\/$/, "") + "/v1" + path,
      {
        method: body === undefined ? "GET" : "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + (await this.accessToken()),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      },
    );
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Trial request failed");
    return result;
  }
  createIntent(workspaceId: string, service: string, wallet: string) {
    return this.request<TrialIntent>("/trials/intents", {
      workspace_id: workspaceId,
      service,
      wallet,
    });
  }
  verifyWallet(intentId: string, signature: string) {
    return this.request<PaymentInstructions>(
      `/trials/intents/${encodeURIComponent(intentId)}/verify-wallet`,
      { signature },
    );
  }
  redeem(intentId: string, transactionId: string) {
    return this.request<TrialEntitlement>(
      `/trials/intents/${encodeURIComponent(intentId)}/redeem`,
      { transaction_id: transactionId },
    );
  }
  entitlements(workspaceId: string) {
    return this.request<{
      subscription: string;
      credits: number;
      trials: {
        service: string;
        expires_at: string;
        credits: number;
        active: boolean;
      }[];
    }>(`/workspaces/${encodeURIComponent(workspaceId)}/entitlements`);
  }
}
