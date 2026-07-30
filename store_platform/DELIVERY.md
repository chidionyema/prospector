# Delivery runbook — get `verify_store.sh` to exit 0

**The probe is the spec. This file only explains what the FAIL lines mean and who fixes them.**

    bash store_platform/scripts/verify_store.sh          # exit 0 sellable · 1 broken · 3 unproven

Exit 3 is not success. A check that could not run is not a check that passed.

## Status 2026-07-30 — `NOT SELLABLE`, exit 1, 4 failures

Green already (do not redo): mints `cs_live_` · `/catalog` 15 packs · MX `5 smtp.google.com`
present · Playwright smoke passes live · `store_platform` clean at HEAD · 518 pytest · 91/91 .NET.

All 4 failures are AC-2 email identity. **None of them need an agent — they are DNS and dashboards.**

| FAIL line | Fix | Where |
|---|---|---|
| `NO SPF on mumchimp.com` | add Postmark's SPF TXT | GoDaddy DNS |
| `NO DKIM at pm._domainkey` | add Postmark's DKIM TXT | GoDaddy DNS |
| `DMARC still points at the GoDaddy default rua` | repoint `rua=` to a mailbox you read | GoDaddy DNS |
| `POSTMARK_SERVER_TOKEN absent from fly secrets` | `fly secrets set` | terminal |

## Step 1 — Postmark (~10 min)

1. Create a Postmark server; verify sender signature / domain for `orders@mumchimp.com`.
2. Postmark shows an SPF and a DKIM record. Add both as TXT in the GoDaddy zone
   (NS = `ns03/ns04.domaincontrol.com`).
   **DO NOT TOUCH MX.** `5 smtp.google.com` is live and receiving today; breaking it silently
   loses refund and privacy-request mail, which is a chargeback feeder.
3. While in the zone, fix DMARC off the GoDaddy default
   (`rua=mailto:dmarc_rua@onsecureserver.net` — nobody reads those) to a mailbox you monitor.
4. ```
   fly secrets set POSTMARK_SERVER_TOKEN=… POSTMARK_FROM_EMAIL=orders@mumchimp.com \
     -a prospector-store-api
   ```
   The machine restarts on secret set. Confirm the startup log no longer prints
   `DELIVERY-DEGRADED` (`MoneyRailConfigGate.cs`).
5. `bash store_platform/scripts/verify_store.sh --quick` → expect 0 failures.

DNS propagates. If SPF/DKIM still FAIL, re-run in ~15 min before debugging — the probe queries
`@8.8.8.8` deliberately, because a stale local resolver cache is not evidence.

## Step 2 — the £49 round trip (AC-1, ~10 min, the proof that matters)

**No real purchase has ever completed in live mode.** Everything else is inference until this runs.

1. Buy one pack for real on https://mumchimp.com.
2. Assert, in order:
   - Stripe shows the charge `paid: true`, 4900 GBP.
   - Success page shows the download **within 40 s** (it polls 20×2 s — `orders/success.tsx:43-63`;
     slower is a FAIL, the page dead-ends).
   - The zip downloads via the presigned R2 URL and its contents match the catalogue promise.
   - The **email** arrives with a working order link (this is why Step 1 comes first).
   - `checkout.session.completed` shows **200** in the Stripe dashboard.
3. Refund it. Assert:
   - `charge.refunded` shows 200; log shows `Reversal … revoked`.
   - The order page returns **410 Gone** (`DeliveryEndpoints.cs:181-189`).
4. Paste the charge id + refund id into `STORY_PRODUCTION_READY.md` → Sign-off.

## Step 3 — turn the reconcile probe on

Only after a **live** Stripe key exists on the machine that runs it:

    python3 store_platform/scripts/reconcile_orders.py --days 7

Then schedule it daily (launchd/cron). It is deliberately **not** scheduled today: the only key
here is a test key, and scheduling would require baking in `--allow-test-mode`, which is exactly
the false-green the probe exists to prevent.

## Deploy safety — read before any `fly deploy`

`fly deploy` ships the **WORKING TREE, not HEAD**. Always:

    bash store_platform/scripts/predeploy_guard.sh && fly deploy …

It exits 1 on a dirty `store_platform/`, so prod stays reproducible from a commit.

Outstanding deploy: the `StripeProvider.cs` statement-descriptor suffix is **built but not
deployed**. The card-statement prefix itself is Dashboard-only —
dashboard.stripe.com/settings/public → `MUMCHIMP` — then
`touch store_platform/.stripe-descriptor-mumchimp` to flip the probe.

## Known-good state to compare against

- Commits `7de8eb0` `6a7bb2a` `8f963a5` `6d2783f` + story commit are **local only**; push is a
  founder call.
- Flaky: `StorageWiringTests.Download_url_honours_a_custom_ttl` — failed once at 90/91, then 91/91
  three times. Mechanism unproven; not a release blocker but do not "fix" it blind.
- `lint` is deliberately NOT a CI gate: 9 errors sit in `pages/pack/[id].tsx` (buy button) and
  `orders/success.tsx` (delivery poller). Refactor those **after** Step 2 passes, never before —
  `[id].tsx:96-99` records that key-gating that file once caused a silent sales outage.
