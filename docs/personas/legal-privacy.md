# The platform for legal and privacy

**What this is.** A field-by-field audit of every piece of personal data the estate holds, what the
published policy promises about it, where code and promise disagree, and what the product claims
about other people's businesses. Measured 2026-08-18 against the working tree at `192aa0e4`.

**Read this if** you are answering a data subject request, reviewing the privacy policy against
reality, deciding whether a retention promise is kept, or asking what legal exposure the product
itself creates.

**The headline, first.** The published privacy policy makes five specific retention promises
(`store_platform/src/Store.Web/src/pages/privacy.tsx:151-160`). **No code in this estate deletes
personal data on any schedule.** Section 4 proves it. That is the single largest legal gap here and
it is a compliance failure, not a design preference.

Siblings: [security.md](security.md) for who can reach the data;
[data-engineer.md](data-engineer.md) for where every byte physically lives;
[content-management.md](content-management.md) for who writes the words a buyer reads. The factual
spine is [../ESTATE_MAP.md](../ESTATE_MAP.md).

---

## 1. Every piece of personal data held

Two databases hold data about people. Everything else in the estate is about businesses and ideas.

### 1.1 The store database (`prospector-store-api`)

SQLite on Fly volume `store_data`, 1 GB, region `lhr`, encrypted at rest
(`fly volumes list -a prospector-store-api`). Connection string at
`store_platform/src/Store.Api/Program.cs:26`, provider at `:28`.

**`Order`** — `store_platform/src/Store.Catalog/Domain/Order.cs:10-22`

| Field | Line | Personal? | Why held | Lawful basis claimed |
|---|---|---|---|---|
| `Id` | `:12` | no | primary key | — |
| `PaymentProvider` | `:13` | no | `"stripe"` | — |
| `ProviderTransactionId` | `:14` | pseudonymous | links to Stripe | contract |
| **`BuyerEmail`** | **`:15`** | **yes** | deliver the pack, support | contract, Art. 6(1)(b) |
| `PackId` | `:16` | no | what was bought | — |
| `AmountPence` | `:17` | no | financial record | legal obligation |
| `Currency` | `:18` | no | financial record | legal obligation |
| **`Country`** | **`:19`** | **yes, weakly** | tax and currency | legal obligation |
| `Status` | `:20` | no | fulfilment state | — |
| `CreatedAt` | `:21` | no | ordering, retention clock | — |

`PackId` is nullable on purpose (`Order.cs:7-8`): a paid-but-unfulfillable sale is captured rather
than dropped, so the money is never lost even when the product is unknown.

**`Entitlement`** — `store_platform/src/Store.Catalog/Domain/Entitlement.cs:9-29`

| Field | Line | Personal? | Note |
|---|---|---|---|
| **`BuyerEmail`** | `:17` | **yes** | duplicated from `Order` |
| **`GrantToken`** | `:18` | **yes, as a credential** | 256-bit CSPRNG, unique-indexed at `StoreDbContext.cs:120` |
| `ContentKey` | `:23` | no | the exact object sold, snapshotted |
| `ContentVersion` | `:24` | no | pin, so a republish never changes what a buyer owns |
| **`ExpiresAt`** | `:25` | no | **always `null` in practice — see §4.2** |
| `DownloadCount` | `:27` | behavioural | how many times this person downloaded |
| `LastDownloadedAt` | `:28` | behavioural | when this person last downloaded |

`DownloadCount` and `LastDownloadedAt` are behavioural data about an identified person. They are
written on every download at `DeliveryEndpoints.cs:261-262`. They are not mentioned in the privacy
policy's list of what is collected. Gap L6.

**`PendingDelivery`** — configured at `StoreDbContext.cs:55-71`

Holds **`BuyerEmail`** capped at 320 characters (`:65`, RFC 5321 maximum) and `LastError` capped at
500 (`:66`). `EntitlementId` is uniquely indexed (`:61`) and that uniqueness is what makes enqueueing
idempotent — the comment at `:58-60` says the database is the only thing that can see a concurrent
insert. Deletion cascades from the entitlement (`:67-70`), which matters for erasure: deleting an
entitlement takes its pending delivery with it.

**`WaitlistSignup`** — configured at `StoreDbContext.cs:92-101`

| Field | Line | Note |
|---|---|---|
| **`Email`** | `:99` | max 320. Indexed at `:97`, deliberately **not unique** (`:95-96`: one person may ask about several gaps, each with its own consent evidence) |
| **`Query`** | `:100` | max 500. The search term the person typed — free text, and therefore potentially self-identifying |
| `CreatedAt` | `:98` | indexed |
| consent hash | — | SHA-256 of the exact sentence shown (`WaitlistService.cs:43-44`) |
| consent version | — | `"waitlist-2026-07-30"` (`WaitlistService.cs:35`) |
| IP hash | — | salted SHA-256 (`WaitlistService.cs:51-56`) |

**The IP handling here is the best privacy engineering in the estate.**
`WaitlistService.cs:51-56` salts the IP before hashing, and returns `null` for a missing address
rather than hashing the string `"unknown"` — the comment at `:47-49` explains that hashing
`"unknown"` would collide every such caller into one bucket that looks like a real identity. That
reasoning is correct and worth copying.

The consent version constant at `WaitlistService.cs:32-35` exists so a later change to the sentence
is distinguishable in the evidence rather than silently merged. That is what makes consent provable
a year later.

**`SalesAudit`** — `store_platform/src/Store.Catalog/Domain/SalesAudit.cs:3-13`

Holds `ProviderTransactionId`, `ProviderProductId`, `AmountPence`, `Currency`, **`Country`** (`:11`)
and `OccurredAt`. **No email.** This is the authoritative financial record for a whole transaction
and it is deliberately built without a direct identifier. Good design: the seven-year financial
retention obligation attaches to a table that is nearly anonymous.

**`AnalyticsEvent`** — `store_platform/src/Store.Catalog/Domain/AnalyticsEvent.cs:19-38`

| Field | Line | Note |
|---|---|---|
| `Name` | `:24` | server-side allowlist, **never free text** (`:23`) |
| `Path` | `:27` | **pathname only, never query strings**, which can carry tokens (`:26`) |
| `Meta` | `:35` | for `checkout_completed` this is the Stripe session id — identifies an order, not a person, and is already in the buyer's own URL (`:29-34`) |
| `CreatedAt` | `:37` | — |

Migration `20260731124037_DropAnalyticsSessionId` shows a session id was removed from this table.
The direction of travel is toward less identification, which is the right direction.

### 1.2 Identity tables — the accounted path

These exist and are populated only if someone creates an account. Migration
`20260731211947_AddIdentity`.

**`StoreUser`** (`StoreDbContext.cs:151-162`) extends ASP.NET Identity: `Email`,
`NormalizedEmail`, `UserName`, `PhoneNumber`, `TosVersionAccepted`, `StripeCustomerId`. Identity
also brings `PasswordHash`, `SecurityStamp` and the `AspNetUserLogins` / `AspNetUserTokens` tables.

**`UserProfile`** — `store_platform/src/Store.Catalog/Domain/Identity/UserProfile.cs:18-37`

| Field | Line |
|---|---|
| `UserId` | `:28` |
| **`FirstName`** | `:29` |
| **`LastName`** | `:30` |
| **`Phone`** | `:31` |
| **`Bio`** | `:32` (free text about a person) |
| **`Website`** | `:33` |
| **`AvatarUrl`** | `:34` |
| **`Country`** | `:35`, defaults to `"GB"` (`:25`) |
| `UpdatedAt` | `:36` |
| **`LastLogin`** | `:37` (behavioural) |

`Bio`, `Website` and `AvatarUrl` are not mentioned anywhere in `privacy.tsx`. The policy's section 1
lists "your email address, name (if provided)" (`privacy.tsx:46`) and stops. Gap L6.

**`RevokedToken`** — `store_platform/src/Store.Catalog/Domain/Identity/RevokedToken.cs:19` carries an
`ExpiresAt`. This is the only entity in the estate with a real expiry semantic.

### 1.3 The engine store — what is NOT here

The 707 MB engine store at `/Users/chidionyema/Documents/code/prospector/store` holds **no buyer
data**. Proved this session:

```
python3 -c "... scan every line of store/prospector.jsonl for keys matching email|buyer|customer ..."
→ PII-ish keys found in ledger: NONE  hits 0
```

907,556 lines, 0 bad lines, 0 buyer-shaped keys. Full method and event tabulation in
[data-engineer.md](data-engineer.md) §3.

A raw pattern scan finds **39 lines** in the ledger containing an email-like string. Every sample
inspected is contact detail from a *retrieved third-party web page*, for example
`... Rockville, Maryland 20852 Telephone: +1 301 770 2920 Fax: ... Email: raps@raps.org` — the
Regulatory Affairs Professionals Society's public contact address, captured as part of a cited
passage. That is third-party business contact data incidentally retrieved, not buyer data, and it
belongs to §7 rather than to §1.

### 1.4 What Stripe holds that we do not

| Data | Stripe | Us |
|---|---|---|
| Card number, expiry, CVC | yes | **never** |
| Cardholder name | yes | **no** |
| Full billing address | yes | **no** — only the country |
| Buyer email | yes | yes (`Order.BuyerEmail`) |
| Billing country | yes | yes (`Order.Country`) |
| Payment method fingerprint | yes | **no** |

The extraction is `StripeProvider.cs:133-135`: email from `session.CustomerDetails?.Email` with
`session.CustomerEmail` as fallback, country from `session.CustomerDetails?.Address?.Country ?? ""`.
Two fields, nothing more.

`privacy.tsx:52-56` describes Stripe as an "independent data controller for the card data it
processes". That is the standard and defensible characterisation.

**No Stripe Customer object is created during checkout.** `StoreUser.StripeCustomerId`
(`StoreDbContext.cs:161`) is populated only if an account is linked later.

---

## 2. What is deliberately not held

Each of these is an active choice with a line of code behind it. They are the strongest part of the
privacy posture.

| Not held | Enforced at | The reasoning, in the code |
|---|---|---|
| Card data | Stripe-hosted checkout | never enters our process |
| Raw client IP | `WaitlistService.cs:51-56` | salted hash, or `null` |
| A hash of `"unknown"` for a missing IP | `WaitlistService.cs:47-49` | would collide every such caller into a fake identity |
| Query strings in analytics | `AnalyticsEvent.cs:26` | a query string can carry a grant token |
| Free-text analytics event names | `AnalyticsEvent.cs:23` | server-side allowlist only |
| An analytics session id | migration `20260731124037_DropAnalyticsSessionId` | removed after it shipped |
| A buyer account, on the default path | §3 | there is nothing to breach |
| Advertising or analytics cookies | `privacy.tsx:93-96` | "only the cookies strictly necessary to process your order" |
| A direct identifier on the financial audit record | `SalesAudit.cs:3-13` | the 7-year table has no email |
| Email bounce webhooks | `MailjetEmailSender.cs:107` comment | not stored |

---

## 3. The accountless model as a privacy posture, and its limits

**The posture.** The default buyer never creates an account. There is no password, no session, no
profile. What replaces the account is a 256-bit CSPRNG token in a link
(`TokenGenerator.cs:8-15`). Data minimisation is achieved structurally rather than by policy: we do
not hold a password because there is no password.

**Limit one: the token is a bearer credential, so possession is entitlement.** Anyone holding the
link downloads. `DeliveryEndpoints.cs:230-237` caps total presigned-URL mints per entitlement, and
that cap is the only bound on how far a shared link spreads.

**Limit two, and this is the one that matters legally: we cannot authenticate a data subject.** An
email arriving that says "delete my data" cannot be verified against anything. There is no account
to log into, no password to prove, no second factor. Answering it means trusting the From header.

Under UK GDPR Art. 12(6) a controller may request additional information to confirm identity where
there are reasonable doubts. In practice the only proof a buyer can offer is the grant token or the
Stripe transaction id from their receipt — both of which arrived in the same inbox we are being
asked to trust. **This is a documented gap and it needs a human decision on process, not code.**
Gap L3.

**Limit three: the accounted path also exists** (§1.2), so "we hold no accounts" is not a true
statement about the estate. Anyone answering a data subject request must check both populations.

---

## 4. Retention: what is promised versus what happens

### 4.1 The five promises

`store_platform/src/Store.Web/src/pages/privacy.tsx:151-160`, verbatim from the rendered list:

| # | Line | Promise |
|---|---|---|
| P1 | `:154` | Order records "retained for 7 years from the date of purchase to comply with UK financial record-keeping obligations, **then securely deleted or anonymised**" |
| P2 | `:155` | Security and access logs "retained for **up to 90 days, then deleted**" |
| P3 | `:156` | Transactional email metadata "retained for **up to 12 months, then deleted**" |
| P4 | `:157` | Download tokens: "**expired tokens are purged within 30 days of expiry**" |
| P5 | `:158` | Waitlist sign-ups "retained for **up to 24 months** from sign-up, then deleted. We delete your record sooner if you withdraw consent" |

### 4.2 What the code actually does

**Nothing on a schedule.** Two searches, both run this session:

```
rg -n "RetentionDays|retention|PurgeAsync|CleanupAsync|DeleteRange" --glob '*.cs' store_platform/src/
  → only three hits, none of them a purge:
      RevokedToken.cs:19        ExpiresAt = expiresAt
      FulfilmentService.cs:89   ExpiresAt = null
      IdempotencyFilter.cs:60   ExpiresAt = DateTime.UtcNow.Add(Ttl)

rg -n "AddHostedService" store_platform/src/Store.Api/
  → Program.cs:101  DeliverySweeper       (sends owed emails)
    Program.cs:108  MoneyRailConfigGate   (startup config check)
```

**There are exactly two background services and neither deletes anything.**

A separate sweep for user-deletion code found `LogoutCommand.cs:50` deleting an auth *cookie* and
`TokenRevocationService.cs` revoking tokens. **No user deletion, no purge, no anonymisation, no
erasure endpoint exists in `Store.Api`.**

### 4.3 Promise by promise

| # | Status | Proof |
|---|---|---|
| P1 | **Not implemented.** No 7-year sweep exists, and there is no anonymisation routine to call | §4.2 |
| P2 | **Not implemented,** and probably not even defined. No log retention configuration found. Fly's own log retention is a separate, shorter window we do not control | §4.2 |
| P3 | **Not implemented.** `MailjetEmailSender.cs:107` notes bounce webhooks are not stored; delivery metadata lives at Mailjet, so this is Mailjet's retention setting and nothing verifies it | §4.2 |
| P4 | **Vacuously true and materially wrong.** `FulfilmentService.cs:89` sets `ExpiresAt = null` on every entitlement it creates. **No token ever expires**, so "expired tokens are purged" is a statement about an empty set. A reader takes it to mean download links stop working. They do not | `FulfilmentService.cs:80-90` |
| P5 | **Not implemented.** No 24-month waitlist sweep. The consent-withdrawal half is manual and the policy says "by emailing us" (`privacy.tsx:179`), so that half is honest about being human-operated | §4.2 |

**P4 is the sharpest.** The mechanism is deliberate — `Entitlement.cs:20-23` explains that
`ContentKey` is snapshotted so a republish never changes what a buyer downloads, which is the
deliver-as-sold guarantee. A permanent entitlement is a *product* decision that makes sense. It just
contradicts a sentence on the live privacy page.

### 4.4 The fix, stated as a choice

Two options and they are genuinely different:

1. **Make the code match the policy.** Write one hosted service that runs daily: delete waitlist
   rows older than 24 months, anonymise orders older than 7 years, set an `ExpiresAt` on new
   entitlements. Cost: **two to three days**, plus a decision on what "anonymise an order" means
   when `SalesAudit` already holds the financial record without an identifier — which suggests
   nulling `Order.BuyerEmail` and `Entitlement.BuyerEmail` is sufficient and safe.
2. **Make the policy match the code.** Rewrite `privacy.tsx:151-160` to say what is true: order
   records retained indefinitely, download links do not expire, waitlist records retained until
   withdrawal. Cost: **one hour** of writing plus counsel review.

**Option 2 is not a soft option.** "Retained indefinitely" with no stated period is itself a UK GDPR
Art. 5(1)(e) storage-limitation problem. The honest sequence is: do option 2 today so the published
statement is true, then do option 1 and update the page again. A false retention statement in a
privacy notice is worse than an unflattering true one.

---

## 5. Data subject requests: could we answer one today?

### 5.1 Access — yes, by hand, with a caveat

The queries exist. Against the store database:

```sql
SELECT * FROM Orders        WHERE BuyerEmail = ?;
SELECT * FROM Entitlements  WHERE BuyerEmail = ?;
SELECT * FROM PendingDelivery WHERE BuyerEmail = ?;
SELECT * FROM WaitlistSignup  WHERE Email = ?;
SELECT * FROM AspNetUsers   WHERE NormalizedEmail = UPPER(?);
SELECT p.* FROM UserProfile p JOIN AspNetUsers u ON p.UserId = u.Id WHERE u.NormalizedEmail = UPPER(?);
```

Every one of those columns is indexed or small enough not to need it: `WaitlistSignup.Email` is
indexed at `StoreDbContext.cs:97`, `Entitlement.GrantToken` at `:120`.

`SalesAudit` **cannot** be searched by email — it holds no identifier
(`SalesAudit.cs:3-13`). It is reachable only by joining `ProviderTransactionId` back through
`Order`. Anyone assembling an access response must remember that join or they will miss the
financial rows.

**Three caveats.**

1. **There is no endpoint, no script and no console action for this.** It is `sqlite3` on a Fly
   volume, run by a human with shell access. `privacy.tsx:183` promises a response within one
   calendar month, which is achievable manually at current volume and will not be at ten times it.
2. **Stripe holds data we would have to request separately** — full billing address, payment method
   details. A complete access response requires a Stripe dashboard export as well.
3. **We cannot verify who is asking** (§3, limit two).

**Verdict: possible today, manual, undocumented, and it will not scale.** Gap L1.

### 5.2 Erasure — partially, and one part is legally blocked

| Data | Erasable? | How |
|---|---|---|
| `WaitlistSignup` | **yes, cleanly** | `DELETE FROM WaitlistSignup WHERE Email = ?`. Consent is the basis (`privacy.tsx:179`), so withdrawal means deletion with no counterweight |
| `UserProfile` | yes | delete the row |
| `AspNetUsers` and Identity tables | yes | ASP.NET Identity supports it; no code calls it |
| `Order.BuyerEmail` | **no, for 7 years** | legal-obligation basis. Nullable the email, keep the row |
| `Entitlement` | **conflict** | deleting it revokes a paid entitlement. Cascade at `StoreDbContext.cs:67-70` takes `PendingDelivery` with it |
| `AnalyticsEvent` | not applicable | holds no identifier by design |
| `SalesAudit` | not reachable by email | and holds no identifier anyway |

The `Entitlement` conflict is the one needing a human decision. A buyer asking for erasure who then
loses access to a pack they paid for has a complaint. The defensible answer is to null `BuyerEmail`
on both `Order` and `Entitlement` while keeping `GrantToken` alive, so the link keeps working and
the person is no longer identified. **Nothing implements that.** Gap L2.

### 5.3 Portability — the same manual queries, plus a format

Art. 20 requires "structured, commonly used and machine-readable". A JSON dump of the §5.1 query
results satisfies it. No tooling exists.

### 5.4 Rectification, restriction, objection

`privacy.tsx:174-178` promises all four. `UserProfile.UpdatePersonalInfo` (`UserProfile.cs:45`)
gives self-service rectification to accounted users. For everyone else all four are manual database
edits with no audit trail of who made them.

---

## 6. Payment and tax

### 6.1 Currency and country

`store_platform/src/Store.Api/Endpoints/CheckoutEndpoints.cs:117` reads the `Fly-Client-Country`
header to determine currency and country. That is Fly's geo-IP header — an inference from network
location, not a declaration by the buyer, and it is what selects the currency before payment.

The authoritative country arrives afterwards from Stripe:
`StripeProvider.cs:135` takes `session.CustomerDetails?.Address?.Country ?? ""`. So there are **two
country values in play**: one guessed at checkout to pick the currency, one collected by Stripe from
the actual billing address. They can disagree, and the stored `Order.Country` is the Stripe one.

`UserProfile.Country` (`UserProfile.cs:35`) is a third, user-editable, defaulting to `"GB"`. It is
not used for tax.

The estate has already made one deliberate decision here: **US buyers are billed in USD.**

### 6.2 VAT and sales tax — the honest state

`rg -n "VAT|Tax|SalesTax" --glob '*.cs' store_platform/src/` over the domain and endpoint code found
**no tax calculation, no tax rate table, no VAT registration number, and no tax line on any
entity.** `Order` holds `AmountPence` and `Currency` and nothing else financial
(`Order.cs:17-18`). `SalesAudit` is the same (`SalesAudit.cs:9-11`).

**HYPOTHESIS: tax is handled entirely by Stripe Tax, configured in the Stripe dashboard rather than
in this repository.** That is the normal arrangement and it is consistent with the absence of any
tax code here. **The exact check that would confirm or kill it:** open the Stripe dashboard,
Settings → Tax, and confirm whether Stripe Tax is enabled and which registrations exist; then check
one live `checkout.session.completed` payload for `total_details.amount_tax`.

**Until that check is run, treat the following as unknown and do not assume they are handled:**

- Whether UK VAT is charged on UK sales, and whether the business is VAT-registered at all.
- Whether EU VAT MOSS / OSS applies to digital services sold to EU consumers. Digital products to EU
  consumers attract VAT in the consumer's member state from the first euro — there is no threshold.
- Whether US state sales tax nexus has been triggered anywhere.
- Whether the seven-year record-keeping promise at `privacy.tsx:154` is met by data Stripe holds
  rather than data we hold.

**This is a human decision item and it is the highest-consequence unknown in this document.** Gap L4.

### 6.3 Who the controller is

`privacy.tsx:27-31` names the operator as data controller and cites UK GDPR and the Data Protection
Act 2018. The legal entity name, address and contact email come from a `LEGAL` constants object
imported into the page (`privacy.tsx:167`, `:219`). The sub-processor list at `privacy.tsx:110-137`
names Stripe (`:116-117`), Mailjet as a Sinch Email brand (`:127-129`), and hosting (`:133`).

`privacy.tsx:124` carries a comment worth quoting because it states the standard correctly:
**"Naming the wrong one is a false statement in a UK GDPR notice."** That is the bar every entry in
the sub-processor list has to meet, and it is the bar §7 and §8 below apply to the model providers.

---

## 7. Retrieval and third-party terms of service

### 7.1 What we fetch and what we keep

The engine fetches third-party web pages as evidence. Three artefacts persist that content, all
measured this session:

| Artefact | Size | Entries | Shape |
|---|---|---|---|
| `store/citation_archive.json` | 292,421 B (288 K) | **1,260 URLs** | `{url: {memento, ts}}` |
| `store/lint_url_cache.json` | 398,990 B (392 K) | **2,914 URLs** | `{url: {status, note, ts}}` |
| `store/_cache/` | **172 MB** | **33,845 files** | `{v, fetched_at, sources}` per file |

Measured with `python3 -c "import json; d=json.load(open(...)); print(len(d))"` and
`ls store/_cache | wc -l`, `du -sh store/_cache`.

Writers, from a code sweep: `prospector/store.py:279` calls `archive_sources()` with
`cache_path=self._root / "citation_archive.json"`, gated on `listing.archive_citations` and
`listing.archive_at_vet`. `prospector/bridge.py:1037` writes the archive; `bridge.py:1123` sets
`url_cache_path=(store_dir / "lint_url_cache.json")`. The retrieval cache directory is
`prospector/retrieval.py:46`, `CACHE_DIR = store_root() / "_cache"`.

The archive keys are the raw URLs. Sampled: `http://stayregular.net/blog/how-to-get-certified-for-metrc`,
`http://voltexelectrical.net/index-19.html`. These are small third-party sites.

### 7.2 The copyright and ToS question, stated plainly

**We store excerpts of other people's web pages, at scale, on our own disk, indefinitely, and we
quote them in a product we sell.** No robots.txt check, no ToS check and no licence check exists
anywhere in the retrieval path. Every one of the following is an open risk:

- **Copyright.** A retrieved passage is someone else's expression. UK law has no fair-use doctrine;
  it has narrowly-drawn fair-dealing exceptions, and "quotation" (CDPA s.30(1ZA)) requires that the
  use be fair, that the work has been made available to the public, and that there be sufficient
  acknowledgement. Our packs *do* cite the source, which helps the acknowledgement limb. Fairness and
  proportion are untested.
- **Terms of service.** Many sites forbid automated access in their terms. We do not read those
  terms and could not act on them if we did.
- **Database right.** Sui generis database right (UK/EU) can attach to a substantial extraction from
  a structured source, independently of copyright.
- **`store/_cache/` at 172 MB across 33,845 files is a substantial corpus** of third-party content
  held on a laptop, on a path under `~/Documents` that syncs to iCloud.

**The passage-length limit is our best mitigating fact, and it is real.** `verify.py:717` sets
`VERDICT_PASSAGE_TRUNCATE = 600`, so each source contributes at most 600 characters to a verdict.
`verify.py:506-508` applies it. Six hundred characters with attribution is a quotation, not a
reproduction.

**This needs counsel, not an engineer's judgement.** Gap L5.

### 7.3 A structural irony worth naming

The product's own robots.txt (`store_platform/src/Store.Web/src/pages/robots.txt.tsx:50-63`) is
carefully written to control AI crawlers, with a comment at `:50-51` explaining that a crawler
matching a specific `User-agent` group ignores the `*` group completely. We ask crawlers to respect
our rules. Our own retrieval path does not read anyone else's. That asymmetry is not itself
unlawful and it is not a defence either.

---

## 8. Model provider terms: what leaves the estate

Every model call sends the prompt to a third party. What is in that prompt determines the exposure.

| Provider | Key location | What is sent | Personal data? |
|---|---|---|---|
| **MiniMax** | `MINIMAX_API_KEY` on engine and Hermes | candidate JSON, check questions, up to 600 chars per retrieved passage (`verify.py:506-518`) | **no buyer data.** Third-party page content, which may incidentally include business contact details (§1.3) |
| **Exa** | `EXA_API_KEY` on engine and Hermes | search queries | no |
| **Anthropic** | `ANTHROPIC_API_KEY` on Hermes only | operator conversation | operator's own words |
| **OpenAI** | `OPENAI_API_KEY` + `OPENAI_BASE_URL` on Hermes | operator surface | operator's own words |
| **Gemini** | `GEMINI_API_KEY` on Hermes | operator surface | operator's own words |
| **DeepSeek** | `DEEPSEEK_API_KEY` on Hermes and `.env` | non-critical generation and triage | no |
| **Browserbase** | `BROWSERBASE_*` on Hermes | browsing sessions | whatever is browsed |
| **SearXNG** | self-hosted, `prospector-searxng` | search queries | no — and self-hosting is why no third-party rate limit sits in the critical path |

**No buyer personal data reaches any model provider.** The engine store contains no buyer-shaped
keys (§1.3), and the store API makes no model calls.

Two things the sub-processor list at `privacy.tsx:110-137` does **not** name: MiniMax and Exa. They
are correctly omitted **if and only if** they never process personal data. Per §1.3 and §7.1 the
data they receive is third-party web content and business contact details, not our customers' data.
That reasoning is sound but it is a judgement, and the retrieved-page contact addresses (§1.3) make
it a judgement about someone else's personal data rather than about our buyers'. Gap L8.

`RSI_SIGNING_KEY` and the two `STANDARD*_COMPUTE_API_KEY` names on Hermes are legacy — see
[security.md](security.md) gap G7.

---

## 9. The legality gate in the product

### 9.1 What it claims to assess

`legality` is one of the six universal checks. The question, from `prospector/models.py:73-76`:

> "Is the margin lawful — achievable without breaking law/terms or falsifying a measurement? A
> creative but lawful workaround — exploiting a legitimate statutory mechanism or a permitted
> loophole — is NOT a fail; only a margin that cannot exist without genuine illegality/breach
> counts."

The polarity is fixed in `prompts/verdict.md`: `supported` means the margin does **not** require
breaking the law; `refuted` means the margin **cannot exist** without breaking the law or falsifying
data. A mere terms-of-service violation counts as `refuted`, because the provider prohibits it and
so the business is contractually blocked.

**That polarity is inverted relative to every other check**, where `supported` normally means the
proposition holds. For `legality` and for `incumbency`, `supported` is the good outcome and the
gate map has to be configured accordingly. The estate has an open note on exactly this
(`moat-polarity-framing-contradiction`), and it is the single most error-prone thing about this
check.

### 9.2 What it actually does

`prospector/kill_filter.py` is 70 lines of pure code over the verdicts, no model
(`kill_filter.py:1`). The gate function is `is_hard_fail(check_name, result, cfg)` at `:20`.

Four rules, in order, each with its line:

1. `:28-29` — `price_comparables` can **never** kill, whatever config says. Enforced in code rather
   than by omission from `hard_gates`, because `hard_gates` is config and a config edit passes
   through neither review nor the test suite (`:22-27`).
2. `:34-35` — a check whose retrieval failed wholesale can never trip a gate. This is the line that
   stops an infrastructure outage masquerading as a grounded kill (`:30-33`).
3. `:42-43` — kill **only** on a cited killing verdict. `unverifiable` and silence never kill
   (`:39-41`).
4. `:51` — and only when `result.confidence >= cfg.thresholds.confidence_floor`.

`apply_gates` at `:54-70` walks `cfg.hard_gates` in config order and returns at the first hard fail.
`adversarial_decisive` is handled as its own gate key at `:60-62`.

**So `legality` does not do anything special.** It is a name in a config list. The behaviour is the
verdict polarity in the prompt plus the generic gate machinery. Everything hangs on the prompt
wording being right and on `hard_gates` naming the correct killing verdict for the inverted
polarity.

### 9.3 The receipts on disk

`sqlite3 store/prospector.db "SELECT gate_fired, COUNT(*) FROM dossiers GROUP BY gate_fired ORDER BY 2 DESC"`,
2,995 rows total:

| Gate fired | Count |
|---|---|
| `moat_ungrounded` | 1,042 |
| `min_composite` | 753 |
| `incumbency` | 271 |
| `source_or_die` | 256 |
| `value_durability` | 202 |
| *(empty — passed or deferred)* | 162 |
| `adversarial_decisive` | 154 |
| `payer_solvency` | 60 |
| **`legality`** | **30** |
| `distribution` | 22 |
| `currency` | 14 |
| `route_to_market` | 13 |
| `pain_reality` | 9 |
| `buyer_intent` | 7 |

Decisions: `kill` 2,842, `pass` 108, `defer` 45.

**A worked legality kill, opened this session.** `store/dossiers/f2f79b96f2147f3d.kill.json`,
`gate_fired: "legality"`, verdict `refuted`, confidence `0.724`. Its rationale:

> `[e7482fd9df282e89]` and `[a7f1c5d31d7fa3f0]` establish that under 705 ILCS 205/1, no person may
> receive compensation for legal services or hold themselves out to provide legal services in
> Illinois without a license; `[959abdd76a91dc8f]` characterizes applying legal principles to a
> user's specific facts and drafting custom legal documents as the practice of law under that
> statute.

Three cited sources, a named statute, and a specific jurisdiction. **This is what the gate is
supposed to produce and it is producing it.** Two further legality kills are at
`store/dossiers/83f0b8ab787e18d0.kill.json` and `store/dossiers/d579daa8befc42bc.kill.json`.

Each check in a dossier carries `check_name`, `verdict`, `confidence`, `rationale`, `citations`,
`sources`, `queries`, `query_source`, `degraded`, `retrieval_failed`, `provider`, `provisional`,
`untraceable_figures`. The `degraded` and `retrieval_failed` flags are how you tell a real legal
finding from an outage.

### 9.4 Where it has been wrong

Two receipts, both on disk, both about the same class of failure.

**The kill produced by our own outage.** `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL on
`min_composite` whose seven checks all read `unverifiable, conf 0.0, "Verdict call failed;
fail-safe."` A candidate killed by an outage, in a dossier that reads as fully reasoned. That is why
`kill_filter.py:34-35` and the DEFER gate at `verify.py:693` exist: a failed call now returns
`retrieval_failed=True` (`verify.py:365`) and defers instead of contributing an `unverifiable` check
to the gates.

**The quarantined ungrounded population.** `sqlite3 store/prospector.db "SELECT tombstone,
COUNT(*) FROM dossiers GROUP BY tombstone"` returns `quarantined_ungrounded` for **9** rows, and
`dossier_missing` for **180**. Twenty-six rows carry `retrieval_degraded = 1`. Those are the rows
whose verdicts — legality among them — were reached against degraded evidence.

**The honest statement about the legality gate: it fires rarely (30 of 2,995), it cites real
statutes when it does, its polarity is inverted relative to most checks and that has caused
confusion before, and 1,042 kills in the same index are `moat_ungrounded` — meaning the most common
outcome by far is that we could not get evidence at all, not that we assessed legality and found a
problem.**

---

## 10. Content liability: what the product claims and what disclaims it

### 10.1 The disclaimers exist, and they are on the storefront, not in the pack

`rg -in "disclaimer|not legal advice|no warranty" prospector/ publish/` returns **75 hits, all in
`publish/preview/packs.html`** — which is generated preview output, not a renderer. A direct search
across the sixteen `prospector/pack_*.py` renderers and `prospector/dossier.py` for disclaimer
language returns **nothing**.

**So no `pack_*.py` renderer emits a disclaimer.** The disclaimers live in the storefront:

| Surface | File |
|---|---|
| Shared disclaimer component | `store_platform/src/Store.Web/src/components/Disclaimer.tsx` |
| The one-sentence limit | `store_platform/src/Store.Web/src/lib/disclaimer.ts` |
| Terms page | `store_platform/src/Store.Web/src/pages/terms.tsx` |
| Refund page | `store_platform/src/Store.Web/src/pages/refund.tsx` |
| Buy drawer | `store_platform/src/Store.Web/src/components/checkout/BuyDrawer.tsx` |
| Pack detail page | `store_platform/src/Store.Web/src/pages/pack/[id].tsx` |
| Marketing layout | `store_platform/src/Store.Web/src/components/marketing/MarketingLayout.tsx` |

`Disclaimer.tsx:12-20` is the full text. It disclaims financial, investment, legal and tax advice,
states that "AI-generated content may contain errors, omissions, or outdated information", places
due-diligence responsibility on the buyer, and says past opportunity signals do not indicate future
results.

`Disclaimer.tsx:7` carries its own warning: **"Draft legal copy, review with qualified counsel
before go-live."** That instruction is still sitting in the file. Gap L7.

### 10.2 The one-sentence limit, and why it was consolidated

`store_platform/src/Store.Web/src/lib/disclaimer.ts:31-32`:

```ts
export const PACK_DISCLAIMER =
  'A pack is evidence-backed research, not a promise of business success.';
```

The header comment at `:1-21` is the best piece of legal reasoning in the codebase and deserves
quoting. The same promise had been typed at four render sites in three different wordings, measured
2026-08-15:

```
pages/how-it-works.tsx:385           "not a guarantee"
components/checkout/BuyDrawer.tsx:184 "not a promise of business success"
pages/pack/[id].tsx:523              "not a promise of business success"
pages/pricing.tsx:156                "not a promise of outcome"
```

The reasoning at `:16-18`: this is the one sentence that limits what is being sold, it appears
immediately before the buy button on two of those four surfaces, and **"under the CPUTR/DMCCA reading
the site already applies to its own copy, the WEAKEST wording is the one a reader can hold us to."**
Plus the maintenance argument: whoever edits it next finds three of the four and leaves the fourth.

`:27-29` explains the word choice: "business success" beats "outcome" because a reader can decide
the outcome they had in mind is covered, and it beats "not a guarantee" because that denies the
strength of the claim without denying its subject.

There is a test pinning this: `store_platform/src/Store.Web/src/__tests__/disclaimerSaidOnce.test.ts`.

### 10.3 The licence and liability terms

`terms.tsx:61` grants a "non-sublicensable licence" to access, read and use pack content.
`terms.tsx:66` forbids reselling, redistributing, sublicensing or otherwise making the content
available to third parties. `terms.tsx:131` caps aggregate liability at the amount paid for the
relevant pack. `terms.tsx:137-138` preserves the non-excludable liabilities: death or personal
injury caused by negligence, and fraud. `terms.tsx:144-145` states the IP position: content,
prompts and formatted output are owned by or licensed to the entity, and the clause-2 licence is the
full grant.

### 10.4 The exposure that remains

**The product makes evidence-backed factual claims about named third-party businesses.** A kill
dossier says a named company's margin cannot exist without breaking a named statute. A pass dossier
says a named incumbent is or is not a real threat. Those are statements of fact about identifiable
businesses, published and sold.

Three distinct risks, and the disclaimers address only the first:

1. **Reliance by the buyer.** Covered by §10.1 and §10.2 and the liability cap at `terms.tsx:131`.
2. **Defamation of the business described.** A false factual statement damaging a business's
   reputation. The defence is truth, and our defence is unusually strong: verdict-from-retrieval-only,
   every claim cited, and the `source_or_die` gate (256 kills). But 26 rows carry
   `retrieval_degraded = 1` and 9 are `quarantined_ungrounded`, so the defence is not uniform across
   the corpus.
3. **The kill log is published.** `store_platform/src/Store.Web/src/pages/kill-log.tsx` exists. A
   public page saying a named business fails a legality check is the highest-exposure single artefact
   in the product. Whether the live kill-log page names companies is a question for whoever reviews
   it — **HYPOTHESIS: it renders candidate titles rather than named incumbents.** The check:
   `rg -n "title|company|incumbent" store_platform/src/Store.Web/src/pages/kill-log.tsx` and then
   load the live page.

---

## 11. Invariants, and what breaks when they go

| # | Invariant | Enforced by | What breaks |
|---|---|---|---|
| L-I1 | No card data enters our process | Stripe-hosted checkout | PCI DSS scope lands on us |
| L-I2 | Raw IPs are never stored | `WaitlistService.cs:51-56` | IP retention with no basis and no retention period |
| L-I3 | Analytics never stores query strings | `AnalyticsEvent.cs:26` | Grant tokens leak into an analytics table |
| L-I4 | Analytics event names are an allowlist | `AnalyticsEvent.cs:23` | Free text becomes an unbounded PII surface |
| L-I5 | `SalesAudit` holds no direct identifier | `SalesAudit.cs:3-13` | The 7-year table becomes a 7-year PII table |
| L-I6 | Consent text is hashed with a version | `WaitlistService.cs:35,43-44` | Consent stops being provable |
| L-I7 | A kill is cited evidence, never opinion | `kill_filter.py:39-43` | Defamation exposure with no truth defence |
| L-I8 | A failed retrieval never trips a gate | `kill_filter.py:34-35` | Our outage becomes a published claim about a business |
| L-I9 | The pack limitation is one sentence in one file | `lib/disclaimer.ts:31-32`, `disclaimerSaidOnce.test.ts` | The weakest of four wordings becomes the binding one |
| L-I10 | The sub-processor list names every processor | `privacy.tsx:110-137`, `:124` | A false statement in a UK GDPR notice |
| L-I11 | `price_comparables` can never kill | `kill_filter.py:28-29` | A fact about the web becomes a claim about a business |

---

## 12. Open legal questions — every one needs a human decision

| # | Question | Evidence | Who decides | Cost to close |
|---|---|---|---|---|
| **L1** | Access and portability requests are manual `sqlite3` with no runbook, no script and no console action | §5.1 | Founder + counsel | **1 day** for a script, 2 hours for a runbook |
| **L2** | Erasure conflicts with a paid entitlement. Is nulling `BuyerEmail` while keeping `GrantToken` alive the policy? | §5.2, `StoreDbContext.cs:67-70` | Counsel | **Half a day** to decide, 1 day to implement |
| **L3** | We cannot authenticate a data subject. What proof do we accept? | §3 limit two | Counsel | **2 hours** to write the policy |
| **L4** | **VAT / sales tax is unverified.** No tax code exists in this repo. EU digital-services VAT has no threshold | §6.2 | **Founder + accountant, urgently** | Unknown until the Stripe dashboard is checked. Potentially significant back-liability |
| **L5** | Copyright, ToS and database-right exposure from 33,845 cached pages and 1,260 archived citations | §7 | Counsel | **1 day** of review; the 600-char limit is the mitigating fact |
| **L6** | The policy does not list everything held: `DownloadCount`, `LastDownloadedAt`, `UserProfile.Bio`, `.Website`, `.AvatarUrl` | §1.1, §1.2, `privacy.tsx:46` | Counsel review of the page | **2 hours** |
| **L7** | `Disclaimer.tsx:7` still says "Draft legal copy, review with qualified counsel before go-live" and the site is live | `Disclaimer.tsx:7` | Counsel | **2 hours** of review |
| **L8** | MiniMax and Exa are not on the sub-processor list. Correct only if they never process personal data — and retrieved pages carry third-party contact details | §8, §1.3 | Counsel | **2 hours** |
| **L9** | **The five retention promises are not implemented.** Nothing deletes anything on a schedule | §4 | Founder decides option 1 or option 2 | **1 hour** to correct the page; **2-3 days** to implement |
| **L10** | Download links never expire (`ExpiresAt = null`), while the policy implies they do | `FulfilmentService.cs:89` vs `privacy.tsx:157` | Founder — it is a product decision first | Folded into L9 |
| **L11** | Does the public kill log name identifiable businesses? | §10.4 | Founder + counsel | **1 hour** to check, then a decision |
| **L12** | No breach-notification procedure exists. UK GDPR Art. 33 requires notice to the ICO within 72 hours | no such document found in `docs/` | Founder + counsel | **Half a day** to write |
| **L13** | No Record of Processing Activities (Art. 30). This document is the closest thing that exists | this file | Counsel | **Half a day** — most of the content is already in §1 |
| **L14** | No Data Processing Agreement is recorded with Mailjet or Stripe. `privacy.tsx:133` asserts hosting operates "under a data-processing agreement" | `privacy.tsx:133` | Founder | **2 hours** to locate and file them |

**Do L4 first.** It is the only item with a compounding financial cost, and the check that resolves
it takes ten minutes in the Stripe dashboard.

**Do L9 option 2 second.** Correcting a false statement on a live privacy page is one hour of work
and it removes a standing misstatement.

---

## 13. How to change any of this safely

1. **Editing `privacy.tsx` is a legal act, not a copy change.** Every sentence in it is a
   representation to a regulator. The comment at `:124` is the standard: naming the wrong processor
   is a false statement in a UK GDPR notice.
2. **Adding a personal-data field requires four edits, not one:** the entity, the migration, the
   `privacy.tsx` collection list, and the retention list. Landing three of four is how §1.2's
   `Bio`/`Website`/`AvatarUrl` gap happened.
3. **Never widen the limitation sentence.** Change `lib/disclaimer.ts:31-32` and every surface
   changes together — that is the point of the file. `disclaimerSaidOnce.test.ts` fails if someone
   re-types it locally.
4. **Never let a check kill on `unverifiable`.** `kill_filter.py:39-43` is the truth defence for
   every published claim about a named business.
5. **Never add a check to `hard_gates` without checking its polarity.** `legality` and `incumbency`
   are inverted relative to the others, and the gate map has to name the correct killing verdict.
6. **Never log a buyer email into the engine ledger.** §1.3 is currently a clean separation and it
   is worth keeping — it is the reason the 707 MB store is out of scope for a data subject request.
7. **Any change to retention needs a decision on L9 first.** Implementing a sweep against a policy
   we intend to rewrite wastes the work.

---

## 14. Where to look next

- [security.md](security.md) — who can reach the data, and the CI runner rule.
- [data-engineer.md](data-engineer.md) — where every byte physically lives, backups, and restore.
- [content-management.md](content-management.md) — who writes the words on the storefront.
- [buyer.md](buyer.md) — the same transaction from the other side of the counter.
- [../ESTATE_MAP.md](../ESTATE_MAP.md) — the factual spine.

### Commands that answer a legal question live

```bash
# What personal data exists, by table
sqlite3 <store.db> ".schema Orders" ".schema Entitlements" ".schema WaitlistSignup"

# Is anything deleted on a schedule? (expect: nothing)
rg -n "RetentionDays|PurgeAsync|CleanupAsync|DeleteRange" --glob '*.cs' store_platform/src/
rg -n "AddHostedService" store_platform/src/Store.Api/

# Do download tokens expire? (expect: ExpiresAt = null)
rg -n "ExpiresAt" store_platform/src/Store.Api/Services/FulfilmentService.cs

# How often has the legality gate fired?
sqlite3 store/prospector.db "SELECT gate_fired, COUNT(*) FROM dossiers GROUP BY gate_fired ORDER BY 2 DESC;"

# How much third-party content do we hold?
python3 -c "import json;print(len(json.load(open('store/citation_archive.json'))))"
ls store/_cache | wc -l && du -sh store/_cache

# Is the limitation sentence still said once?
rg -n "PACK_DISCLAIMER" store_platform/src/Store.Web/src/
```
