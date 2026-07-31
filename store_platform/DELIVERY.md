# Delivery runbook — get `verify_store.sh` to exit 0

**The probe is the spec. This file only explains what the FAIL lines mean and who fixes them.**

    bash store_platform/scripts/verify_store.sh          # exit 0 sellable · 1 broken · 3 unproven

Exit 3 is not success. A check that could not run is not a check that passed.

## Status 2026-07-30 — `NOT SELLABLE`, exit 1, 4 failures

Green already (do not redo): mints `cs_live_` · `/catalog` 15 packs · MX `5 smtp.google.com`
present · Playwright smoke passes live · 518 pytest · 99/99 .NET.

All 4 failures are AC-2 email identity. **None of them need an agent — they are DNS and dashboards.**

> **Provider changed 2026-07-30 (founder's call): Postmark → Mailjet.** The DNS shape is
> unchanged — SPF + DKIM TXT only, no MX either way — so the work below is the same size it
> always was; only the record values and the selector differ. `PostmarkEmailSender.cs` is
> deleted; `MailjetEmailSender.cs` replaces it and is covered by 8 tests. Committed at `e3dc9d9`;
> `store_platform/` is clean, so `predeploy_guard.sh` passes and a deploy ships exactly that tree.

| FAIL line | Fix | Where | Status |
|---|---|---|---|
| `NO SPF on mumchimp.com` / `SPF … does not contain include:spf.mailjet.com` | add the SPF TXT | 123-reg DNS | **DONE 2026-07-30** — probe PASSes |
| `DMARC still points at the registrar default rua` | repoint `rua=` to a mailbox you read | 123-reg DNS | **DONE 2026-07-30** — probe PASSes |
| `NO DKIM at mailjet._domainkey` | add Mailjet's DKIM TXT | 123-reg DNS | blocked: value only exists after the Mailjet account does |
| `MAILJET_API_KEY absent from fly secrets` | `fly secrets set` | terminal | blocked: same |

Both remaining failures are downstream of one thing that cannot be delegated to Claude: **creating
the Mailjet account.** Claude is barred from creating accounts or entering passwords regardless of
authorisation, so the DKIM value and the API key pair must come from the founder. Everything after
that point — the DKIM DNS record, `fly secrets set`, deploy, re-probe — Claude can do.

## Step 1 — Mailjet (~10 min)

1. Create a Mailjet account (free tier: 6k/mo, 200/day, no KYC) and add the sending domain
   `mumchimp.com`, then the sender `orders@mumchimp.com`.
2. Add the records at **123-reg**: <https://dcc.123-reg.co.uk/control/dnsmanagement?domainName=mumchimp.com>
   → *Add New Record*. Not GoDaddy — the nameservers are `ns03/ns04.domaincontrol.com`, but the
   nameserver host is not the registrar, and three docs used to send you to the wrong panel.

   Zone as observed 2026-07-30 (`dig`, and the 9-record 123-reg listing): `A @`, `AAAA @`,
   `NS @` ×2, `SOA @`, `CNAME api` → `prospector-store-api.fly.dev.`, `CNAME www` →
   `prospector-store-web.fly.dev.`, `MX @` `5 smtp.google.com.`, `TXT _dmarc`.
   **There is NO `TXT @` record at all** — `dig +short TXT mumchimp.com @8.8.8.8` is empty.

   | Action | Type | Name | Data | |
   |---|---|---|---|---|
   | **Add** | TXT | `@` | `v=spf1 include:_spf.google.com include:spf.mailjet.com ~all` | ✅ done 2026-07-30 |
   | **Edit** | TXT | `_dmarc` | `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:support@mumchimp.com;` | ✅ done 2026-07-30 |
   | **Add** | TXT | `mailjet._domainkey` | the `k=rsa; p=MIIB…` value Mailjet generates for this account | ⬜ needs the account |

   The zone now holds **10** records. Do not re-add the SPF row — a second `v=spf1` is a permerror.
   If Mailjet's verification wizard offers to add SPF for you, **decline it** and point the wizard
   at the existing record; its suggested value omits `include:_spf.google.com`.

   The SPF value is **not** the one Mailjet's wizard will show you. Mailjet shows
   `v=spf1 include:spf.mailjet.com ?all`. Pasting that verbatim authorises Mailjet and
   **de-authorises Google** — and `MX 5 smtp.google.com` means you send from Google Workspace as
   `@mumchimp.com`. Today there is no SPF at all, so Google mail is merely unauthenticated;
   a Mailjet-only record makes it an explicit SPF **fail** under the live `p=quarantine`. Both
   includes, one record. (`theintroexchange.com` runs `include:spf.mailjet.com ?all` — it has no
   Google MX, so it does not need the second include. Don't copy it here.)

   **Add, don't append a second `v=spf1`.** Two SPF records is a permerror. There is none today,
   so this is a clean create — but re-check `dig +short TXT mumchimp.com` at the moment you edit,
   in case Mailjet's verification wizard added one first.

   **DO NOT TOUCH MX, A, AAAA, or the api/www CNAMEs.** `5 smtp.google.com` is live and receiving
   today; breaking it silently loses refund and privacy-request mail, which is a chargeback
   feeder. Mailjet needs no MX. The A/AAAA/CNAMEs are what serve the shop: apex and www both
   answer 200 from `66.241.124.37`, which is `prospector-store-web`'s shared v4 ingress
   (`fly ips list -a prospector-store-web`).
3. DMARC `rua` currently goes to `dmarc_rua@onsecureserver.net`, a registrar default nobody
   reads. `support@mumchimp.com` receives (MX verified above), so it is the obvious target.
   Keep `p=quarantine` — do not relax it to `p=none` to make bring-up easier; quarantine is why
   the missing SPF matters, and lowering it hides the problem instead of fixing it.

   HYPOTHESIS, untested: SPF alone may not be enough for order email to pass DMARC, making the
   DKIM record load-bearing rather than merely good hygiene. Mailjet sends with its own bounce
   domain as the envelope-from, and DMARC SPF alignment (even relaxed, `aspf=r`) compares the
   *envelope-from* domain to the header `From:` domain — so an SPF pass for a Mailjet bounce
   domain does not align with `mumchimp.com`, and DKIM becomes the only path to a DMARC pass.
   Check: after adding the records, send one order email to a Gmail address and read
   `Authentication-Results` under *Show original* — `dmarc=pass` is the answer either way.
4. ```
   fly secrets set MAILJET_API_KEY=… MAILJET_API_SECRET=… \
     MAILJET_FROM_EMAIL=orders@mumchimp.com -a prospector-store-api
   ```
   Mailjet authenticates with a key PAIR — the public API key and the private secret. Setting
   only one leaves the sender reading as unconfigured (deliberate: a half-set pair 401s on every
   send, which would otherwise look like a provider outage rather than a config mistake).
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
