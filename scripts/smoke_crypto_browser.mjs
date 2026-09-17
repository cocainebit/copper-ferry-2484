// Invoked by smoke_crypto_browser.py against disposable localhost services only.
import { chromium, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
const base = 'http://127.0.0.1:3108';
const account = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
const errors = [];
let signatures = 0;
page.on('pageerror', error => errors.push(error.message));
try {
  await page.exposeBinding('signLocalTestAuthorization', async (_source, typedData) => {
    const data = JSON.parse(typedData);
    if (data.domain.chainId !== 31337 || data.message.from.toLowerCase() !== account.toLowerCase()) throw new Error('Refusing non-test signing request');
    signatures++;
    return execFileSync(process.env.CUBICLE_TEST_PYTHON, ['-c', `import json,sys
from eth_account import Account
from eth_account.messages import encode_typed_data
# Public Anvil development key, never a real wallet.
key='0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
data=json.load(sys.stdin)
assert data['domain']['chainId']==31337
print('0x'+Account.from_key(key).sign_message(encode_typed_data(full_message=data)).signature.hex())`], {input: typedData, encoding: 'utf8'}).trim();
  });
  await page.addInitScript(({account}) => {
    sessionStorage.setItem('use-local-workspace', 'true');
    window.ethereum = {request: async ({method, params}) => {
      if (method === 'eth_chainId') return '0x7a69';
      if (method === 'eth_requestAccounts') return [account];
      if (method === 'eth_signTypedData_v4') return window.signLocalTestAuthorization(params[1]);
      throw new Error('Unexpected wallet method: '+method);
    }};
  }, {account});
  await page.goto(base+'/app?view=billing');
  await expect(page.getByRole('heading', {name: 'A little room to grow.'})).toBeVisible({timeout: 60000});
  await expect(page.getByText(/Test network · Test USDC only/)).toBeVisible();
  await page.getByRole('button', {name: 'Create payment invoice',exact:true}).click();
  await expect(page.getByRole('heading', {name:'10 USDC invoice'})).toBeVisible();
  await page.getByRole('button', {name:'Authorize payment in wallet',exact:true}).click();
  await expect(page.getByText('Paid',{exact:true})).toBeVisible({timeout:60000});
  await expect(page.getByText('Payment confirmed. Your platform balance is ready.')).toBeVisible();
  await expect(page.locator('.billing-price')).toHaveText('10 USDC');
  await expect(page.getByRole('article',{name:'Balance activity'})).toContainText('Credit · +10 USDC');
  await expect(page.locator('.error-banner')).toHaveCount(0);
  await page.getByRole('button',{name:'Check payment status',exact:true}).click();
  await expect(page.locator('.billing-price')).toHaveText('10 USDC');
  if (signatures !== 1 || errors.length) throw new Error(JSON.stringify({signatures,errors}));
  await mkdir('test-results',{recursive:true});
  await page.screenshot({path:'test-results/crypto-browser-paid.png',fullPage:true});
  console.log('PASS: actual browser UI → TypeScript EIP-712 → real signature → API invoice → facilitator → Anvil transfer → paid UI and 10 USDC ledger, one signature, no browser errors');
} finally {
  await browser.close();
}
