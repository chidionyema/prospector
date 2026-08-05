# Mumchimp.com — Current State for Specialist Review

## Landing Page Structure (top to bottom)

### 1. Header
Dark green (#042F2E), 56px. White logo, nav links (Catalog, Browse by category, How it works, FAQ), cart, account.

### 2. Hero
Centered. Eyebrow "Stress tested business ideas · £49 each". H1 headline (copy-driven). Subheadline. Ghost/outline CTA "Read a free report, no email". Text below: "No payment, no email. A whole dossier, unredacted, every source clickable."

### 3. Trust Band
3-column row. "6 rigorous checks", "100% sourced", "Ready to build" — each with icon + description. Warm paper bg, tan borders.

### 4. Catalog Section
- **Toolbar**: Search input (⌘K), sort dropdown, pack count
- **Progressive 3-step flow**: "What skills do you bring?" → "How much time can you commit?" → "Who do you want to sell to?" Large tappable cards, multi-select for skills, single-select for others. After completion: summary with "Edit your answers" + "Advanced filters" expander.
- **Removable filter chips** (when filters active)
- **Trending picks row**: 3 compact cards, top packs by source count
- **SpotlightCard**: Hero card for newest pack, offset shadow, "Latest to survive" badge, "View vetted blueprint" CTA + Buy button
- **Recently viewed row**: 3 cards from localStorage
- **Grid**: ~60 left-rule document cards (3px green left border, warm paper bg, no shadows, no rounded corners). Each card: category icon, category label in teal, "Trending" badge (if 30+ sources), font-bold heading, bolded first sentence of description, 6-segment green verification bar, proof line (sources + freshness), "Unlock for £49" primary CTA, "or view details" link
- **Guarantee**: "Every pack carries a 14 day money back guarantee"
- **Email waitlist CTA**

### 5. "What you get for £49"
Deliverable list (8 documents), trust pills (£49 one time, 14 day refund, every claim sourced, instant download), dossier preview, price comparison (method cost anchor), "Why £49 once, not another subscription" comparison table.

### 6. Trust Band (dark)
Dark green bg. "Why you can trust this" heading, 4 bullet points, links to kill log and how-it-works.

### 7. Footer
3-column link grid. Support email, response time.

## Key Pages

| Page | Current State |
|------|---------------|
| **Pack detail** | Left-rule header, "Survived six checks" teal badge, deliverables, scored axes, purchase panel, "Back to catalog" link |
| **FAQ** | Accordions, live search, category pills, "Was this helpful?" feedback |
| **Kill log** | Search bar, filter pills, struck-through rejected ideas with reasons |
| **How it works** | Stepped timeline of 6 gates, kill examples |
| **Ideas** | Rich category cards with icons, search, trending row |
| **Sample** | Free dossier preview, verdict badges, source citations |
| **Account** | Auth/sign-in, orders panel |
| **Basket** | Right-drawer modal, trust badges, sticky footer |

## Design System

| Token | Value |
|-------|-------|
| Background | #FEFDF9 (warm paper) |
| Surface | #FEFDF9 |
| Borders | #D4C9B5 (tan) |
| Text | #1A1A1A |
| Muted | #78716C (stone) |
| Primary | #042F2E (deep green) |
| Verification | #0D9488 (teal) |
| Font | Hanken Grotesk (single family, 3 weights) |
| Cards | Left-rule, no shadows, no rounded corners |
| Buttons | Squared, solid green |

## Open Questions for Review

1. Too many sections before products? (Hero → Trust → Toolbar → Flow → Chips → Trending → Spotlight → Grid = 8 steps)
2. Progressive flow should be default-visible or collapsed?
3. Trending picks + Recently viewed + SpotlightCard — too many pre-grid rows?
4. Trust messaging is redundant (hero badges + section 6)?
5. "What you get" section should be above or below the catalog?
6. Pack detail page: cover killed, replaced with left-rule. Good direction?
7. CTA copy: "Unlock for £49" vs alternatives?
