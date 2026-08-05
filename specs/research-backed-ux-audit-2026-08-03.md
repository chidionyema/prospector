# Mumchimp.com — Research-Backed UX Audit 2026-08-03

## Research Sources

- ZipChat, "Product Discovery Patterns for Ecommerce" (2026)
- Emerge Digital, "E-commerce UI/UX in 2026: Designing Experiences That Convert"
- Splitsense, "SaaS Landing Page Best Practices: 14 Proven Tips" (2026)
- Constructor, "Beyond Relevance" (March 2025) — 609M searches across 113 retailers
- Baymard Institute — avg site search zero-results rate: 12-18%
- Pixelhop, "Don't Make Me Use Filters" (2026)
- Contra Collective, "Headless Ecommerce Generative Search" (2026)

## Key Research Findings

### Discovery is the #1 growth lever
- Searchers are 24% of visitors but drive 44% of revenue and 45% of add-to-cart
- Searchers convert 2.5x faster than non-searchers
- Fixing discovery captures more revenue than tuning checkout

### The 5 discovery maturity levels
1. Keyword search — exact text matching (2-4% conversion, 12-18% zero-results)
2. Semantic search — meaning-based matching (4-7% conversion)
3. Conversational search — chat-based discovery
4. Guided discovery — structured questions (quiz → results)
5. Agentic discovery — AI operates the catalogue

**Mumchimp is at level 4 (guided discovery)** via the progressive 3-step flow. This is ahead of ~90% of ecommerce stores that plateau at level 1-2.

### 2026 user expectations
- Speed, clarity, confidence at every step
- Mobile-first is baseline, not strategy
- Personalization through UX, not pop-ups
- Product page is "where trust is built or lost"
- Zero tolerance for friction

### SaaS landing page best practices (8-section model)
1. Hero (value proposition)
2. Social proof
3. Problem/solution
4. Features
5. How it works
6. Pricing
7. FAQ
8. CTA

## Current Site Assessment

### Mumchimp vs. 8-section model
| Section | Mumchimp | Assessment |
|---------|----------|------------|
| Hero | Headline + ghost CTA | ✅ Clean, strong |
| Social proof | Trust band (3 pillars) | ✅ Good |
| Problem/solution | Missing | ❌ No "why this exists" narrative |
| Features | "What you get for £49" | ✅ Below catalog (misplaced) |
| How it works | Trust band (dark) + /how-it-works link | 🟡 Buried below catalog |
| Pricing | £49 everywhere | ✅ Clear |
| FAQ | /faq page | ✅ Separate page |
| CTA | "Unlock for £49" on every card | ✅ Strong |

### Critical issue: 15 sections, not 8
The page has nearly double the recommended sections. The progressive flow sits in a box between the toolbar and the grid — the #1 growth lever is buried below the fold.

### Progressive flow: right tool, wrong placement
The guided discovery (level 4 on the maturity curve) is excellent. But it sits below a toolbar, a trust band, and above filter chips, trending, recently viewed, and a spotlight card before the buyer sees the first product card.

## Recommendations

### 1. Move progressive flow into the hero (CRITICAL)
The guided discovery IS the product. It should be the first thing after the headline, not buried in a box below the toolbar.

Current: Hero → Trust band → Toolbar → [Flow in box] → Chips → Trending → ... → Grid
Target: Hero (headline + flow integrated) → Cards appear as you answer

### 2. Reduce to 8 sections
- Cut: Trending picks row, recently viewed row, separate trust band
- Move: "What you get" above the catalog or inline with cards
- Merge: Trust messaging into the hero and cards (verification bar already does this)

### 3. SpotlightCard: consider removing
The SpotlightCard ("Latest to survive") is the largest card on the page and competes with the progressive flow for attention. The flow already personalizes results — the spotlight is redundant.

### 4. Verification as ambient trust, not a section
The 6-segment green bar on every card already performs the trust function. The dark trust band repeats the same message. Keep the bar, cut the band.

## Files Affected
- `pages/index.tsx` — CatalogBrowser layout, hero, sections
- `components/discovery/StepFlow.tsx` — already extracted, ready for hero integration
- `components/discovery/FacetBar.tsx` — StepFlow component
