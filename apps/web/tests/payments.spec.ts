import { test, expect } from "@playwright/test";
import {
  signInvoice,
  validateInvoice,
  type Invoice,
  type BillingOverview,
} from "../../../packages/platform-billing/src";
const quote = {
  network: "eip155:84532",
  asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
  recipient: "0x1111111111111111111111111111111111111111",
};
function invoice(): Invoice {
  return {
    id: "invoice-test",
    status: "open",
    amount_micro_usdc: 10000000,
    expires_at: new Date(Date.now() + 600000).toISOString(),
    ...quote,
    payment_required: {
      x402Version: 2,
      resource: {
        url: "https://cubicle.example/v1/payment-invoices/invoice-test/pay",
      },
      accepts: [
        {
          scheme: "exact",
          network: quote.network,
          asset: quote.asset,
          payTo: quote.recipient,
          amount: "10000000",
          maxTimeoutSeconds: 300,
          extra: {
            name: "USDC",
            version: "2",
            invoiceNonce: "0x" + "ab".repeat(32),
          },
        },
      ],
    },
  };
}
const overview = (): BillingOverview => ({
  enabled: true,
  ...quote,
  test_network: true,
  balance_micro_usdc: 2000000,
  prices: [{ service: "cubicle", unit: "minute", price_micro_usdc: 3334 }],
  invoices: [],
  entries: [
    {
      id: 1,
      service: "cubicle",
      amount: -6668,
      units: 2,
      unit_price: 3334,
      reason: "Desktop usage",
      created_at: "2026-09-17T02:00:00Z",
    },
  ],
});
test("signature matches invoice and validates payment recipient before wallet access", async () => {
  const item = invoice();
  let signed: any;
  const payload = await signInvoice(
    {
      request: async ({ method, params }) => {
        if (method === "eth_chainId") return "0x14a34";
        if (method === "eth_requestAccounts") return [quote.recipient];
        if (method === "eth_signTypedData_v4") {
          signed = JSON.parse(params![1] as string);
          return "0x" + "cd".repeat(65);
        }
        throw new Error(method);
      },
    },
    item,
    quote,
    10000000,
  );
  const decoded = JSON.parse(atob(payload));
  expect(signed.primaryType).toBe("TransferWithAuthorization");
  expect(signed.domain.chainId).toBe(84532);
  expect(signed.message.nonce).toBe(
    item.payment_required!.accepts[0].extra!.invoiceNonce,
  );
  expect(decoded.accepted).toEqual(item.payment_required!.accepts[0]);
  expect(decoded.payload.authorization.value).toBe("10000000");
  item.payment_required!.accepts[0].payTo =
    "0x2222222222222222222222222222222222222222";
  expect(() => validateInvoice(item, quote, 10000000)).toThrow(
    /does not match/,
  );
});
test("wallet cancellation never submits payment; pending settles without a second signature", async ({
  page,
}) => {
  let submissions = 0;
  let status = "open";
  await page.route("**/api/v1/workspaces/*/payments", (route) =>
    route.fulfill({ json: overview() }),
  );
  await page.route("**/api/v1/workspaces/*/payments/invoices", (route) =>
    route.fulfill({ json: invoice() }),
  );
  await page.route("**/api/v1/payment-invoices/invoice-test/pay", (route) => {
    submissions++;
    status = "settlement_pending";
    return route.fulfill({ json: { ...invoice(), status } });
  });
  await page.route("**/api/v1/payment-invoices/invoice-test", (route) =>
    route.fulfill({ json: { ...invoice(), status } }),
  );
  await page.addInitScript(() => {
    (window as any).ethereum = {
      request: async ({ method }: { method: string }) => {
        if (method === "eth_chainId") return "0x14a34";
        if (method === "eth_requestAccounts")
          return ["0x1111111111111111111111111111111111111111"];
        if (method === "eth_signTypedData_v4") {
          if (!(window as any).allowPayment)
            throw Object.assign(new Error("User rejected"), { code: 4001 });
          return "0x" + "cd".repeat(65);
        }
      },
    };
  });
  await page.goto("/app");
  await page.getByRole("button", { name: "Billing", exact: true }).click();
  await expect(page.getByText(/Test network · Test USDC only/)).toBeVisible();
  await expect(
    page.getByRole("article", { name: "Balance activity" }),
  ).toContainText("Debit · −0.006668 USDC");
  await expect(
    page.getByRole("article", { name: "Balance activity" }),
  ).toContainText("Cubicle · 2 minute(s) × 0.003334 USDC");
  await page.getByRole("button", { name: "Create payment invoice" }).click();
  await page
    .getByRole("button", { name: "Authorize payment in wallet" })
    .click();
  await expect(page.locator(".error-banner")).toContainText(
    "Wallet request cancelled",
  );
  expect(submissions).toBe(0);
  await page.evaluate(() => {
    (window as any).allowPayment = true;
  });
  await page
    .getByRole("button", { name: "Authorize payment in wallet" })
    .click();
  await expect(page.getByText(/Checking settlement/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create payment invoice" }),
  ).toBeDisabled();
  status = "paid";
  await page.getByRole("button", { name: "Check payment status" }).click();
  await expect(page.getByText("Paid", { exact: true })).toBeVisible();
  expect(submissions).toBe(1);
});
