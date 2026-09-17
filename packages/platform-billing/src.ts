/** Shared prepaid billing client. The server is authoritative for settlement and balances. */
export type Requirement = {
  scheme: string;
  network: string;
  asset: string;
  amount: string;
  payTo: string;
  maxTimeoutSeconds: number;
  extra?: { name?: string; version?: string; invoiceNonce?: string };
};
export type PaymentRequired = {
  x402Version: number;
  resource: { url: string; description?: string; mimeType?: string };
  accepts: Requirement[];
  extensions?: Record<string, unknown>;
};
export type Invoice = {
  id: string;
  status: string;
  amount_micro_usdc: number;
  expires_at: string;
  network: string;
  asset: string;
  recipient: string;
  payment_required?: PaymentRequired;
  transaction?: string;
};
export type BillingEntry = {
  id: number;
  service: string;
  amount: number;
  units: number;
  unit_price: number;
  reason: string;
  created_at: string;
};
export type BillingOverview = {
  entries?: BillingEntry[];
  enabled: boolean;
  reason?: string;
  network: string;
  asset: string;
  recipient: string;
  test_network?: boolean;
  balance_micro_usdc: number;
  prices: { service: string; unit: string; price_micro_usdc: number }[];
  invoices: Invoice[];
};
export interface WalletProvider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}
export class PlatformBilling {
  constructor(
    private baseURL: string,
    private accessToken: () => Promise<string>,
  ) {}
  private async request<T>(
    path: string,
    method = "GET",
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<T> {
    const response = await fetch(
      this.baseURL.replace(/\/$/, "") + "/v1" + path,
      {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + (await this.accessToken()),
          ...headers,
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      },
    );
    const result = await response.json();
    if (!response.ok)
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "Payment request failed. Check invoice status before trying again.",
      );
    return result;
  }
  overview(workspace: string) {
    return this.request<BillingOverview>(
      `/workspaces/${encodeURIComponent(workspace)}/payments`,
    );
  }
  createInvoice(workspace: string, amount: number, idempotencyKey: string) {
    return this.request<Invoice>(
      `/workspaces/${encodeURIComponent(workspace)}/payments/invoices`,
      "POST",
      { amount_micro_usdc: amount },
      { "Idempotency-Key": idempotencyKey },
    );
  }
  invoice(id: string) {
    return this.request<Invoice>(`/payment-invoices/${encodeURIComponent(id)}`);
  }
  pay(id: string, signature: string) {
    return this.request<Invoice>(
      `/payment-invoices/${encodeURIComponent(id)}/pay`,
      "POST",
      undefined,
      { "PAYMENT-SIGNATURE": signature },
    );
  }
}
const address = /^0x[0-9a-fA-F]{40}$/;
const equalAddress = (a: string, b: string) =>
  address.test(a) && address.test(b) && a.toLowerCase() === b.toLowerCase();
/** Validate before requesting wallet access. Only exact EIP-3009 USDC payments are supported. */
export function validateInvoice(
  invoice: Invoice,
  quote: Pick<BillingOverview, "network" | "asset" | "recipient">,
  amount: number,
) {
  const required = invoice.payment_required;
  if (!required || required.x402Version !== 2 || required.accepts.length !== 1)
    throw new Error("Unsupported payment request.");
  const accepted = required.accepts[0];
  if (
    accepted.scheme !== "exact" ||
    !/^eip155:[1-9][0-9]*$/.test(accepted.network) ||
    accepted.network !== quote.network ||
    invoice.network !== quote.network ||
    !equalAddress(accepted.asset, quote.asset) ||
    !equalAddress(invoice.asset, quote.asset) ||
    !equalAddress(accepted.payTo, quote.recipient) ||
    !equalAddress(invoice.recipient, quote.recipient) ||
    !Number.isSafeInteger(amount) ||
    amount <= 0 ||
    invoice.amount_micro_usdc !== amount ||
    accepted.amount !== String(amount)
  )
    throw new Error(
      "Payment request does not match your invoice. No signature was requested.",
    );
  if (
    !Number.isFinite(Date.parse(invoice.expires_at)) ||
    Date.parse(invoice.expires_at) <= Date.now() ||
    !Number.isSafeInteger(accepted.maxTimeoutSeconds) ||
    accepted.maxTimeoutSeconds < 1 ||
    accepted.maxTimeoutSeconds > 3600 ||
    !accepted.extra?.name ||
    !accepted.extra?.version ||
    !/^0x[0-9a-fA-F]{64}$/.test(accepted.extra?.invoiceNonce || "")
  )
    throw new Error(
      "Payment request expired or is invalid. Create a new invoice.",
    );
  return accepted;
}
export async function signInvoice(
  wallet: WalletProvider,
  invoice: Invoice,
  quote: Pick<BillingOverview, "network" | "asset" | "recipient">,
  amount: number,
): Promise<string> {
  const accepted = validateInvoice(invoice, quote, amount);
  const chainId = Number(accepted.network.split(":")[1]);
  if (!Number.isSafeInteger(chainId)) throw new Error("Unsupported chain.");
  const chainHex = "0x" + chainId.toString(16);
  if (
    String(await wallet.request({ method: "eth_chainId" })).toLowerCase() !==
    chainHex
  )
    await wallet.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: chainHex }],
    });
  if (
    String(await wallet.request({ method: "eth_chainId" })).toLowerCase() !==
    chainHex
  )
    throw new Error("Please select the invoice network in your wallet.");
  const accounts = (await wallet.request({
    method: "eth_requestAccounts",
  })) as string[];
  if (!accounts?.[0] || !address.test(accounts[0]))
    throw new Error("No wallet account selected.");
  const now = Math.floor(Date.now() / 1000);
  const authorization = {
    from: accounts[0],
    to: accepted.payTo,
    value: accepted.amount,
    validAfter: String(now - 600),
    validBefore: String(
      Math.min(
        now + accepted.maxTimeoutSeconds,
        Math.floor(Date.parse(invoice.expires_at) / 1000),
      ),
    ),
    nonce: accepted.extra!.invoiceNonce!,
  };
  const typedData = {
    domain: {
      name: accepted.extra!.name,
      version: accepted.extra!.version,
      chainId,
      verifyingContract: accepted.asset,
    },
    primaryType: "TransferWithAuthorization",
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "version", type: "string" },
        { name: "chainId", type: "uint256" },
        { name: "verifyingContract", type: "address" },
      ],
      TransferWithAuthorization: [
        { name: "from", type: "address" },
        { name: "to", type: "address" },
        { name: "value", type: "uint256" },
        { name: "validAfter", type: "uint256" },
        { name: "validBefore", type: "uint256" },
        { name: "nonce", type: "bytes32" },
      ],
    },
    message: authorization,
  };
  const signature = await wallet.request({
    method: "eth_signTypedData_v4",
    params: [accounts[0], JSON.stringify(typedData)],
  });
  if (typeof signature !== "string" || !/^0x[0-9a-fA-F]{130}$/.test(signature))
    throw new Error("Wallet returned an unsupported signature.");
  return btoa(
    JSON.stringify({
      x402Version: 2,
      resource: invoice.payment_required!.resource,
      accepted,
      payload: { signature, authorization },
    }),
  );
}
