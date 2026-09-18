# What the market charges, and what Cubicle should

Researched 2026-09-17. Every figure here was read on the vendor's own page on that date, and the
source is named. Where a number is not published, this document says so rather than estimating it.
Prices move; re-read the sources before acting on anything here.

## 1. The direct competitor does not meter at all

Orgo sells monthly subscriptions capped by how many computers you may have, not by how long they
run. From their docs, verbatim: "Computers are persistent - there's no per-hour metering - but every
computer counts against that plan's cap until you delete it, whether it is running or stopped."

| Plan | Price | Computers | RAM | Storage | Seats | OS |
| --- | --- | --- | --- | --- | --- | --- |
| Hacker | $29/mo | 1 | 8 GB | 40 GB total | 1 | Linux |
| Startup | $99/mo | 4 | 32 GB | 160 GB total | 5 | Linux |
| Scale | $399/mo | 16 | 128 GB | 640 GB total | 25 | Linux + Windows |
| Enterprise | not published | 60+ | | | 50+ | + Mac, GPU fleets |

One computer is capped at 4 vCPU, 64 GB RAM and 300 GB disk on every plan. A free account has a
zero-computer quota: creating one returns `403 UPGRADE_REQUIRED`. There is no free desktop.

Sources: orgo.ai/pricing (read in a browser, the page is client-rendered), docs.orgo.ai/llms-full.txt.

Scrapybara, the other comparable, is gone: the virtual desktop service was sunsetted on
October 15, 2025 and the team moved to a different product.

## 2. The metered vendors have converged on one number

For 2 vCPU and 4 GiB, running:

| Vendor | Rate | Per hour | 730 hours | When stopped or paused |
| --- | --- | --- | --- | --- |
| E2B | $0.000014/vCPU-s + $0.0000045/GiB-s | **$0.1656** | $120.89 | Not billed. Filesystem and memory kept, free, indefinitely |
| Daytona | $0.0504/vCPU-h + $0.0162/GiB-h | **$0.1656** | $120.89 | Disk only; free once archived (7 days) |
| Modal Sandboxes | $0.00003942/core-s + $0.00000667/GiB-s | $0.3799 | $277.30 | Killed, not paused |
| Cloudflare Containers | $0.000020/vCPU-s active + $0.0000025/GiB-s | ~$0.185 at full CPU | varies | CPU billed on active runtime only |
| Orgo | no meter | $0.0397 effective if always on | **$29.00** | Still occupies the slot you pay for |

E2B and Daytona arrive at $0.1656 by completely different arithmetic. That is the market price for
this shape, not a coincidence.

Plan fees sit on top of the meter and buy concurrency, not a discount: E2B Pro $150/mo for 100
concurrent sandboxes, $650 for 600, $1,150 for 1,100. Modal Team $250/mo. Per-second unit rates are
identical across Modal's tiers. No vendor in this research publishes a marginal price for one extra
concurrent slot.

Sources: e2b.dev/pricing, docs.e2b.dev/billing, daytona.io/pricing, daytona.io/docs/en/billing/,
modal.com/pricing, modal.com/docs/guide/billing, developers.cloudflare.com/containers/pricing/.

## 3. Browser infrastructure, the closest time-priced comparable

| Vendor | Pay as you go | Cheapest plan blended | Bandwidth |
| --- | --- | --- | --- |
| Anchor | $0.05/browser-h + $0.01 per browser created | not computable, allowance unpublished | $8/GB, or $0.20/GB bring-your-own |
| Kernel | $0.06/h headless, **$0.48/h headful**, $2.88/h headful+GPU | $0.18/h | free and unlimited, stated |
| Steel | $0.10/h | $0.20/h | $10/GB, $6/GB at scale |
| Hyperbrowser | $0.10/h | $0.10/h, no plan discount | $10/GB |
| Browserbase | $0.12/h overage | $0.20/h | $12/GB, $10/GB at scale |
| Browserless | $0.24/h overage (30s units) | $0.15/h | charged as units |

Two things matter here. Kernel's **headful** browser, the nearest thing to a desktop, is $0.48/hour,
three times what E2B and Daytona charge for a whole sandbox. And every vendor except Kernel bills
bandwidth separately at $8 to $12 per GB on top of the hourly rate.

Note the pattern in the middle column: for Browserbase, Steel and Kernel the subscription's blended
rate is *worse* than their own pay-as-you-go rate. The monthly fee buys concurrency and features, and
customers pay a premium for it rather than a discount.

Sources: docs.anchorbrowser.io/pricing, onkernel.com/pricing, steel.dev/pricing,
hyperbrowser.ai/pricing, browserbase.com/pricing, browserless.io/pricing.

## 4. What a desktop actually costs to run

| Option | Shape | Cost per desktop | Notes |
| --- | --- | --- | --- |
| Hetzner Cloud CX23 | 2 vCPU, 4 GB, 40 GB NVMe | **$6.89/mo, which is $0.0094/h** | Hetzner's own hourly list rate is $0.0110/h, capped at the monthly price. 20 TB traffic included. EUR 5.99 converted at 1.15 |
| Hetzner AX41 dedicated, no overcommit | 6c/12t, 64 GB, EUR 59/mo | $0.0155/h ($11.31/mo) | 6 desktops per box, CPU binds first |
| Hetzner AX41, 2x CPU overcommit | same | $0.0077/h ($5.65/mo) | 12 desktops. The overcommit ratio is our assumption, not Hetzner's |
| Fly.io shared-cpu-2x + 20 GiB volume | 2 vCPU, 4 GB | $0.0338/h | Stopped machines still cost rootfs and volume |
| AWS t4g.medium + gp3 | 2 vCPU, 4 GB | $0.0358/h | |
| GCP e2-medium + PD | 2 vCPU, 4 GB | $0.0346/h | |

Renting one small VM per desktop from Hetzner is cheaper than packing a dedicated AX41 unless you
overcommit CPU by more than 2x. That is worth knowing before anyone builds a packing scheduler: the
saving people expect from bare metal mostly is not there at this size.

Windows costs extra and always will: AWS charges a $4.19 per user per month license fee on
WorkSpaces, Microsoft's Windows 365 Business Cloud PC is $25.60 per user per month for 2 vCPU and
4 GB, and Daytona surcharges $0.0858 per vCPU-hour for Windows. Orgo only offers Windows on its $399
tier, which is consistent with the license being real money.

GPUs, for reference: an H100 is $1.73 to $4.29 an hour depending on vendor and whether the capacity
is preemptible. A 4090 is $0.14 to $0.74.

Sources: hetzner.com/cloud/cost-optimized/, hetzner.com/dedicated-rootserver/ax41/,
fly.io/docs/about/pricing/, aws.amazon.com/ec2/pricing/on-demand/,
cloud.google.com/products/compute/pricing/general-purpose,
aws.amazon.com/workspaces/desktop-as-a-service/pricing/, microsoft.com/en-us/windows-365/business/all-pricing,
runpod.io/pricing, vast.ai, lambda.ai/service/gpu-cloud.

## 5. The gap worth attacking

Orgo's crossover against the metered vendors is at **175 hours a month** ($29 / $0.1656), about 5.8
hours a day.

- Below that, a subscription is brutal. Two hours a month on Orgo is $29, which is $14.50 an hour.
- Above it, metering is brutal. Always-on costs $120.89 at E2B or Daytona against Orgo's $29.

Neither model covers both ends, and the customer cannot know in advance which end they are on. An
agent that runs in short bursts and an agent that sits on a desktop all month are the same product.

## 6. Proposed mechanism: meter by the second, cap by the month

**Charge for running time by the second, and never charge more for one computer in 30 days than the
price of a monthly pass. When a computer reaches the cap, it runs free until the period ends.**

That single rule wins both comparisons. A five minute task costs five minutes, which beats Orgo by
two orders of magnitude at the light end. An always-on desktop costs the cap, which beats E2B and
Daytona by four times at the heavy end. The customer never has to predict their own usage, because
choosing wrong costs them nothing.

Numbers to decide, with the constraints they have to satisfy:

| Lever | Suggested | Floor it must clear | Ceiling it must stay under |
| --- | --- | --- | --- |
| Hourly rate, cpu2-mem4 | $0.10/h | $0.0094/h infrastructure | $0.1656/h market |
| Monthly cap per computer | $19 | $6.89/mo infrastructure | $29 Orgo |
| Stopped computer | free, disk included | negligible | Orgo charges a full slot, Daytona charges disk |

At $0.10 an hour the cap is reached after 190 hours, so anyone running a desktop more than 6.3 hours
a day is effectively on a $19 subscription, and anyone below that is paying strictly less than the
market rate. Margin is roughly 10x on metered hours and 2.8x at the cap. Both of those survive a
doubling of infrastructure cost.

Three supporting decisions:

**Stopped is free, and say so loudly.** This is the clearest difference from both competitors. Orgo's
stopped computer still consumes the slot you pay for; Daytona bills its disk. Cubicle already stops
billing on stop, so this costs nothing to offer and is worth putting on the pricing page as a
sentence rather than leaving it implied.

**Do not sell concurrency separately.** E2B, Modal and Browserbase all gate concurrency by plan tier
and none of them publishes a marginal price for one more slot. Under a per-computer cap, concurrency
prices itself: running four desktops costs four caps at most. That is simpler to explain and it
removes the single most common complaint about these products.

**Keep a hard floor on free.** Fly.io removed its free tier and said why: "Charging a credit card
prevents most at-scale abuse. Abusive users are surprisingly loathe to pay even $5." A USDC rail has
weaker abuse defences than a card, since there is no chargeback and no identity behind a wallet. The
token-holder trial already in Cubicle is the right shape, but a free always-on desktop is not.

## 7. How this maps onto the rail we actually have

The Instance platform charges per action with no stored balance, so Cubicle cannot meter now and
invoice later. The mechanism survives that with one adjustment: sell runtime in prepaid packs, and
consume them by the second.

- A pack is one charge that buys runtime. It is consumed per second while a computer runs, at the
  rate for that computer's tier. The customer sees per-second billing; the platform sees one payment.
- The cap becomes an automatic conversion. When a computer's consumption in a rolling 30 days reaches
  the pass price, it converts to a pass and stops consuming until the period ends.
- Passes stay on sale for anyone who wants to prepay the cap and skip the packs.

This also fixes the current hour-block behaviour, where a desktop stopped after ten minutes has still
been charged for a full hour. That was a workaround for having no hold primitive on the platform, and
a consumable pack is the better answer whether or not a hold ever lands.

## 8. What is still unknown

**Bandwidth per desktop-hour is not measured.** A desktop streams its screen, which the headless
sandbox vendors mostly do not, so their pricing gives no guide. An attempt to measure it here failed:
a background browser tab throttles noVNC's update requests, so the numbers it produced were not real
and are not recorded. It needs a foreground session on a real display, or a scripted RFB client that
requests updates continuously.

The decision does not block on it. Hetzner includes 20 TB per month on both the CX23 and the AX41,
and one desktop would have to push 28 GB an hour continuously for a month to exhaust that. Bandwidth
only becomes a real cost on Fly ($0.02/GB), AWS ($0.09/GB) or GCP ($0.085/GB), which is an argument
about where to host rather than about how to price.

Also unpublished, and worth not guessing at: Orgo's capacity add-on prices, AWS and GCP spot prices
for this shape, and OVH's bandwidth overage rate.
