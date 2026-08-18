# The platform for legal and privacy

What personal data the platform holds, what it claims in public, and where the exposure is.

**This document is a map, not advice.** Several rows below are marked as needing verification rather
than asserted, because getting them wrong in a document is worse than leaving a gap visible.

## Personal data: the good news first

**There are no accounts and no passwords.** The purchase model is deliberately accountless: a buyer
pays, and delivery is a bearer token in a link (`/orders/{token}`, `/download/{token}`). There is no
credential store to breach and no profile to leak.

**Card data never touches this platform.** Checkout creates a Stripe session and the buyer enters
payment details on Stripe. What comes back is a webhook and a session id.

## What is actually held

| Data | Where | Why |
|---|---|---|
| Email address | Store API on the `store_data` volume, from the Stripe session | Delivery of the pack |
| Order and entitlement records | Same | Fulfilment, and the idempotency guard |
| Stripe session and customer ids | Same | Reconciliation |
| Billing country | Same | Currency. US buyers are billed in USD by decision |
| Download token | Same | Access to the purchased pack |
| **No** card numbers, addresses, phone numbers, or behavioural profiles | — | Not collected |

**To verify before relying on this:** the exact retention period, whether IP addresses are logged at
the edge, and what the storefront's analytics (if any) collect. Read
`store_platform/src/Store.Api/` and the storefront's own configuration rather than trusting this
table.

## Data subject requests

A deletion or access request resolves against one database — the store API's, on `store_data`. That
is a genuinely small surface, and it is the main privacy benefit of the accountless model.

**Not built:** there is no self-service deletion, no export endpoint, and no documented process. A
request today is a manual database operation. If volume grows, this is the first thing to build.

## The other side: what the platform says about other people's businesses

This is the more interesting legal surface, and it is unusual.

The product publishes research about markets and, unavoidably, about identifiable companies — an
`incumbency` check exists precisely to establish who already occupies a space. The controls are:

- **Source-or-die.** Every factual claim and every number cites a retrievable source or ships marked
  `unverifiable`. No unsourced assertion about anyone reaches a buyer.
- **Verdict-from-retrieval-only.** The model rules solely on passages it actually fetched. Prior
  knowledge is not admissible, and silence produces `unverifiable`, never a claim.
- **Citations are archived at vet time** (`store/citation_archive.json`), so if a challenge arrives
  months later the passage that supported the claim still exists.

That combination is what makes a published claim defensible: there is a fetched passage behind it,
kept.

**To verify:** how much source text is quoted verbatim in a rendered pack, and whether quoting length
sits inside fair dealing. The renderers are deterministic and inspectable
(`prospector/pack_*.py`), so this is answerable by reading them rather than guessing.

## The legality gate, and a mistake worth knowing about

One of the six hard gates is `legality`. It kills a candidate when cited evidence shows the business
would require breaking a law or terms, or falsifying data.

It was once inverted. It killed on `supported` while every other gate killed on `refuted`, which
meant it **killed lawful ideas for being lawful.** Two receipts are on disk:
`store/dossiers/459b72f3630d21be.kill.json` (heirloom tomatoes — "completely legal to grow, sell,
buy, and eat anywhere in the United States") and `7e603974bcde1e09` ("basic gardening work does not
require a specific licence"). Both killed at confidence 0.43 and 0.42.

The rule now: a creative but **lawful** workaround that exploits a legitimate statutory mechanism must
survive. Only a margin that requires actually breaking law or terms is a kill.

## Retrieval and terms of service

The engine fetches web pages to ground its verdicts. The chain is `[ddg, exa, claude_cli]`, plus a
self-hosted SearXNG instance (`prospector-searxng`) for private search. Caching is in `store/_cache/`.

**To verify:** whether the fetch behaviour respects robots directives and per-source terms. This is
worth a deliberate answer rather than an assumption.

## Consumer-facing obligations

**Not verified in this document, and each needs a real check:**

- Terms of sale, refund policy, and whether they are actually published on `mumchimp.com`.
- The UK distance-selling position on digital goods delivered immediately, and whether the checkout
  captures the right acknowledgement.
- Cookie and consent handling on the storefront.
- VAT and sales-tax treatment. US buyers are billed in USD by decision; what that implies for tax
  registration is a question for an accountant, not for this file.

## Where the AI disclosure question sits

Packs are generated by language models and verified against fetched sources. **To verify:** whether
that is disclosed to buyers, and whether it should be. It is a product and trust question as much as
a legal one, and given that the entire value proposition is "the evidence is checkable", disclosure
probably strengthens rather than weakens the offer.

## What to read next

- [security.md](security.md) — where the data physically sits and who can reach it.
- [buyer.md](buyer.md) — what is promised at the point of sale.
- [product-manager.md](product-manager.md) — the claims the product makes.
