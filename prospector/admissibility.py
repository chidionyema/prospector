"""Citation ADMISSIBILITY — which domains may be the SOLE basis of a ruling.

This is the Q4 lever from `docs/COMMERCIAL_READINESS_PROGRAM.md` §20, and it is deliberately
narrow. Three things it is NOT:

  1. **Not a retrieval denylist.** §18 measured that grounding is RELEVANCE-bound, not
     availability-bound (21.4 citations per `moat_ungrounded` kill, and 0 kills with no
     citations at all). Shrinking the fetched pool is the one intervention that provably
     cannot help, and can starve checks further. Admissibility runs at RULING time: every
     passage is still fetched, still shown to the judge, still stored.
  2. **Not a judgement about "bad websites".** A Reddit thread can be entirely true and still
     be unable to establish what the law says. The question is whether a domain can carry a
     MARKET FACT, per check, not whether it is honest.
  3. **Not a blanket rule.** It is scored PER CHECK. For `distribution` and `route_to_market`
     a Facebook group with 12k members IS the channel being evidenced; for `legality` or
     `payer_solvency` a TikTok cannot establish what the law says or what buyers pay.

Measured basis (§20.3, offline, zero LLM, over `store/dossiers/*.json`)
-----------------------------------------------------------------------
Cost of each candidate policy, counted as RULED verdicts (supported/refuted) that would be
demoted to unverifiable because EVERY one of their citations is inadmissible:

    policy              all eras        current moat
    P0_global           52  (2.02%)     17  (1.38%)
    P1_check_aware      12  (0.47%)      1  (0.08%)
    P2_farm_only         0  (0.00%)      0  (0.00%)

P0 is rejected: it costs 4.3x what P1 costs, and it pays that cost precisely in the checks
where user-generated content was the RIGHT source (its damage is distribution 26,
route_to_market 8). P1 is the shipped default. P2 exists as the free floor.

**Caveat, load-bearing and carried from §20.3:** the tier lists are hand-declared and
evidence-led rather than exhaustive, and the `other` tier is 76.4% of cited evidence and is
unaudited. This bounds the user-generated-content and statistics-farm question only. A domain
sitting in `other` is NOT thereby endorsed.

This module is the SINGLE definition of the tiers. `tools/experiments/q4_citation_source_quality.py`
imports from here rather than keeping its own copy, so the measurement and the shipped gate can
never disagree about what a `stats_farm` is.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse

# --- tier definitions (explicit, auditable, evidence-led) -------------------------------------

GOV_SUFFIXES = (
    ".gov.uk", ".gov", ".nhs.uk", ".police.uk", ".parliament.uk",
    ".judiciary.uk", ".europa.eu", ".gov.au", ".gc.ca",
)
REGULATORS = {
    "fca.org.uk", "ico.org.uk", "legislation.gov.uk", "hse.gov.uk", "ofcom.org.uk",
    "ofgem.gov.uk", "cqc.org.uk", "calbar.ca.gov", "sra.org.uk", "caa.co.uk",
}
ACADEMIC_SUFFIXES = (".ac.uk", ".edu")
ACADEMIC_HOSTS = {
    "pmc.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "sciencedirect.com", "nature.com",
    "bmj.com", "thelancet.com", "springer.com", "jstor.org", "arxiv.org",
}
MEDIA = {
    "bbc.co.uk", "bbc.com", "theguardian.com", "ft.com", "reuters.com", "telegraph.co.uk",
    "thetimes.co.uk", "economist.com", "independent.co.uk", "news.sky.com", "standard.co.uk",
    "inews.co.uk", "mirror.co.uk", "nytimes.com", "wsj.com",
}
ESTABLISHED_ORG = {
    "citizensadvice.org.uk", "carersuk.org", "ageuk.org.uk", "which.co.uk",
    "moneysavingexpert.com", "moneyhelper.org.uk", "mind.org.uk", "scope.org.uk",
    "shelter.org.uk", "acas.org.uk", "unison.org.uk", "rcn.org.uk",
}

# Low-quality FOR THE PURPOSE OF RULING A VERDICT. Not "bad websites" — user-generated and
# reference material can be perfectly true while being unable to establish a market fact.
UGC_SOCIAL = {
    "facebook.com", "m.facebook.com", "web.facebook.com", "youtube.com", "m.youtube.com",
    "youtu.be", "reddit.com", "old.reddit.com", "tiktok.com", "instagram.com",
    "linkedin.com", "uk.linkedin.com", "twitter.com", "x.com", "quora.com", "zhihu.com",
    "pinterest.com", "pinterest.co.uk", "web.whatsapp.com", "whatsapp.com", "tumblr.com",
    "nextdoor.co.uk", "mumsnet.com",
}
REFERENCE_NOISE = {
    "dictionary.cambridge.org", "merriam-webster.com", "thesaurus.com", "dictionary.com",
    "collinsdictionary.com", "vocabulary.com", "urbandictionary.com", "wordreference.com",
    "bodleian.ox.ac.uk",  # library catalogue chrome, not a substantive source
}
# Evidence-led and deliberately short: only domains actually observed behaving as AI/stat farms.
STATS_FARM = {
    "gitnux.org", "gitnux.com", "zippia.com", "wifitalents.com", "sci-tech-today.com",
    "electroiq.com", "worldmetrics.org", "zipdo.co",
}

LOW_TIERS = {"ugc_social", "reference_noise", "stats_farm"}

# The checks where user-generated content CAN be the thing being evidenced. §20.2: exposure
# concentrates in the two channel checks, and that is the evidence being the right shape for
# the question, not contamination.
#
# `buyer_intent` was in this set until 2026-08-14 and was removed, because it asks the one
# question social content cannot answer: whether anyone PAID. `8d5e24fbe6c1f5d3` cited two
# Pinterest boards for a purchasing market — a board is evidence that someone made a mood
# board. A complaint thread genuinely IS the pain (`pain_reality` stays), and a Facebook group
# genuinely IS the channel (`distribution`, `route_to_market` stay); neither is a receipt.
#
# Measured cost of the removal, 2026-08-14, offline over `store/dossiers/*.json` (2,118
# dossiers, 3,476 ruled-and-cited checks): 3 further rulings demote — `buyer_intent` rulings
# whose EVERY citation is `ugc_social`. That moves the §20.3 P1 figure from 12 to 15
# (0.47% → 0.58%); the table in this module's docstring is the ORIGINAL measurement and is
# left as measured rather than back-edited.
UGC_ADMISSIBLE = {"distribution", "route_to_market", "pain_reality"}

# Policy names. `off` is a real option, not a placeholder: it is the pre-§20 behaviour and the
# thing every measurement is stated against.
POLICIES = ("off", "P2_farm_only", "P1_check_aware", "P0_global")


def _in_suffix_family(host: str, suffixes: tuple[str, ...]) -> bool:
    """`host.endswith(".gov.uk")` misses `gov.uk` itself — the apex IS the domain.

    Measured 2026-08-14 over `store/dossiers/*.json`: `gov.uk` and `nhs.uk` were cited at the
    apex and classified `other`, so the government tier did not contain the government. A
    tier list that silently mis-tiers is the one thing a gate cannot be built on.
    """
    return any(host == s.lstrip(".") or host.endswith(s) for s in suffixes)


def tier(host: str) -> str:
    """Classify a bare hostname. Unknown => `other` (76.4% of evidence; unaudited, NOT endorsed)."""
    if host in STATS_FARM:
        return "stats_farm"
    if host in REFERENCE_NOISE:
        return "reference_noise"
    if host in UGC_SOCIAL:
        return "ugc_social"
    if host in REGULATORS or _in_suffix_family(host, GOV_SUFFIXES):
        return "government"
    if host in ACADEMIC_HOSTS or _in_suffix_family(host, ACADEMIC_SUFFIXES):
        return "academic"
    if host in MEDIA:
        return "media"
    if host in ESTABLISHED_ORG:
        return "established_org"
    if host == "en.wikipedia.org" or host.endswith(".wikipedia.org"):
        return "wikipedia"
    return "other"


def host_of(url: str) -> str:
    """Bare hostname: lowercased first, then a LEADING `www.` removed.

    Both details are corrections of the original Q4 expression
    `netloc.replace("www.", "").lower()`, which had two defects:
      * it stripped before lowercasing, so `WWW.Reddit.com` kept its prefix and fell through
        to the `other` tier instead of `ugc_social`;
      * `replace` is unanchored, so `notwww.example.com` became `notexample.com`.
    Neither changed the published §20 numbers (the corpus is lowercase and has no such host —
    re-running the experiment after this fix reproduced the receipts byte-for-byte), but a
    classifier that silently mis-tiers on letter case is not one to build a gate on.
    """
    try:
        netloc = urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


# What a buyer is told about a source, in their words rather than ours. The pack's source
# appendix listed a Pinterest board and a CDC page as visually identical entries — same
# heading, same quote block — which invites a reader to weigh them the same. The tiers are
# already computed for the gate above; printing them is free, and it is the difference
# between "here are 33 links" and "here is what each link is".
#
# `other` is deliberately unlabelled: it is 76.4% of cited evidence and unaudited, so any word
# we printed for it would be a claim we cannot support (this module's docstring, caveat).
PROVENANCE_LABEL = {
    "government": "official source",
    "academic": "academic or peer-reviewed",
    "media": "news report",
    "established_org": "established organisation",
    "wikipedia": "encyclopaedia summary",
    "ugc_social": "user-generated post",
    "reference_noise": "dictionary or reference entry",
    "stats_farm": "statistics aggregator, no named source",
}


def provenance_label(url: str) -> str:
    """Plain-English provenance for a cited URL; `""` when we cannot say (the `other` tier)."""
    host = host_of(url)
    if not host:
        return ""
    return PROVENANCE_LABEL.get(tier(host), "")


def inadmissible_tiers(check_name: str, policy: str) -> frozenset[str]:
    """Which tiers cannot SOLELY carry a ruling for this check, under this policy."""
    if policy == "P0_global":
        return frozenset(LOW_TIERS)
    if policy == "P2_farm_only":
        return frozenset({"stats_farm", "reference_noise"})
    if policy == "P1_check_aware":
        bad = {"stats_farm", "reference_noise"}
        if check_name not in UGC_ADMISSIBLE:
            bad.add("ugc_social")
        return frozenset(bad)
    return frozenset()  # `off` and any unknown policy => no demotion


def is_ruling_admissible(check_name: str, urls: Iterable[str],
                         policy: str = "P1_check_aware") -> bool:
    """True unless EVERY cited URL sits in a tier inadmissible for this check.

    The "every" is the whole design. One good source rescues a ruling, which is why P1 costs
    12 verdicts across two months rather than the 484 rulings that merely TOUCH a low-tier
    domain. A ruling with no citations is not this gate's business — `source_or_die` at
    `verify.py:427` already handles it — so an empty list returns True.
    """
    if policy == "off":
        return True
    tiers = [tier(h) for h in (host_of(u) for u in urls) if h]
    if not tiers:
        return True
    bad = inadmissible_tiers(check_name, policy)
    return not all(t in bad for t in tiers)


# ---------------------------------------------------------------------------------------
# Health and medical statistics — a SECOND, narrower gate, on top of the tier policy
# ---------------------------------------------------------------------------------------
#
# Why a second gate. The tier policy asks "can this KIND of domain carry a market fact?" and
# it answered yes for `8d5e24fbe6c1f5d3`, correctly by its own terms: `jeffreydachmd.com`
# ("Increasing Autism Rate is Caused by Environmental Toxin Says RFK Jr") and
# `playproject.org` ("a 3000% increase!") are neither social nor stats-farms, so both sit in
# `other` and both were admissible. They were cited for a PREVALENCE FIGURE — 1 in 31 US
# children — in a pack sold to people who will market to autism parents, while CDC pages sat
# unused in the same source list.
#
# So the question here is not the domain's kind but the CLAIM's kind: a medical rate is the
# one claim type where a blog restating a primary source is not a substitute for it. This
# fires only when BOTH a medical term and a rate-shaped figure are in the ruling's own words,
# and only demotes when NOT ONE citation is government, academic or an established
# health/consumer body.
#
# Measured 2026-08-14 over `store/dossiers/*.json` (offline, zero LLM): 6 of 3,476 ruled and
# cited checks demote (0.17%) — pain_reality 3, value_durability 1, claims_verifiable 1,
# buyer_intent 1. Cheaper than P1_check_aware, and it fires where the brand risk is.
MEDICAL_PRIMARY_TIERS = frozenset({"government", "academic", "established_org"})

_HEALTH_TERM_RE = re.compile(
    r"\b(autis\w*|asd|adhd|dyslex\w*|dyspraxi\w*|prevalence|diagnos\w+|disorder\w*|syndrome"
    r"|epileps\w*|dementia|alzheimer\w*|vaccin\w+|cancer|diabet\w+|depress\w+|anxiety"
    r"|mental health|clinical\w*|symptom\w*|patients?)\b", re.IGNORECASE)
#: A rate, not any number: "1 in 31", "18%", "prevalence", "incidence". A medical word next
#: to a PRICE is a market fact about a health product, which this gate has no business
#: demoting — the founder's complaint was about an epidemiological figure.
_HEALTH_RATE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?%|\b\d+ in \d+\b|\bprevalence\b|\bincidence\b|\brate of\b",
    re.IGNORECASE)


def is_health_statistic(text: str) -> bool:
    """Does this ruling rest on a medical/epidemiological RATE, in its own words?"""
    t = str(text or "")
    return bool(_HEALTH_TERM_RE.search(t) and _HEALTH_RATE_RE.search(t))


def health_demotion_reason(text: str, urls: Iterable[str],
                           enabled: bool = True) -> Optional[str]:
    """A sentence naming the failure, or None if the ruling stands.

    `enabled` is config-declared (`admissibility.health_claims_need_primary`) so the gate can
    be measured against being off, like every other lever in this programme.
    """
    if not enabled or not is_health_statistic(text):
        return None
    hosts = [h for h in (host_of(u) for u in urls) if h]
    if not hosts:
        return None
    if any(tier(h) in MEDICAL_PRIMARY_TIERS for h in hosts):
        return None
    return ("Ruling demoted to unverifiable: it states a health or prevalence figure, and "
            f"not one of its citations ({', '.join(sorted(set(hosts)))}) is a government, "
            "academic or established health body. A medical rate must come from the body "
            "that published it, not from a site restating it.")


# ---------------------------------------------------------------------------------------
# Corroboration — a THIRD gate, about the number of independent publishers
# ---------------------------------------------------------------------------------------
#
# The two gates above ask what KIND of domain, and what KIND of claim. Neither asks how many
# publishers actually said it. Nothing required a `supported` verdict to rest on more than
# one, so three pages from one site counted as three sources — while every pack tells the
# buyer to pick any SUPPORTED claim, click its source and claim a refund if it does not say
# what we say it says.
#
# Measured 2026-08-14, `tools/experiments/d5_corroboration.py`, offline over all 2,031
# dossiers with checks (independence judged at the REGISTRABLE domain, so
# `assets.publishing.service.gov.uk` and `www.gov.uk` are one publisher):
#   * 470 of 2,816 cited `supported` rulings (16.7%) rest on a SINGLE publisher;
#   * 348 (12.4%) rest on a single citation;
#   * the sole publisher is `other` in 313 (siterecon.ai, sparkreceipt.com),
#     `ugc_social` in 36 (facebook.com 23, youtube.com 4, reddit.com 4) —
#     and `government` in 103 (gov.uk 56, ca.gov 9, fca.org.uk 5, nhs.uk 5).
#
# Hence the exemption, which is the whole design of this gate. A lone `government` or
# `academic` publisher needs no corroboration: `legislation.gov.uk` IS the answer on legality,
# and demanding that a blog agree with it makes the evidence worse, not better. Exempting
# those two tiers spares 108 rulings and costs nothing — replaying all 75 PASS dossiers with
# the affected rulings demoted flips exactly ONE to KILL either way
# (`b94760e86e62585a.pass.json`, lane `growth`, whose `value_durability` cites
# `nhsleavecalculator.co.uk` twice plus two sibling calculator sites). `media` and
# `established_org` are deliberately NOT exempt: one newspaper restating one press release is
# precisely the correlated evidence this gate exists to catch.
#
# SUPPORTED ONLY, enforced at the call site (`verify.py`): a refutation from a single source
# still kills. Corroborating a kill was never measured, and weakening kills is not this
# programme's business.
CORROBORATION_EXEMPT_TIERS: tuple[str, ...] = ("government", "academic")

#: Public suffixes with a second level. NOT the full PSL — the corpus is UK/US/AU/EU, and a
#: missing entry OVER-splits (two publishers where there is one), which makes the gate more
#: permissive. The error direction is deliberate: a gate that invents corroboration would be
#: unsafe, one that occasionally misses it is merely weaker than advertised.
_TWO_LABEL_SUFFIXES: frozenset[str] = frozenset({
    "co.uk", "gov.uk", "org.uk", "ac.uk", "nhs.uk", "police.uk", "sch.uk", "ltd.uk", "me.uk",
    "com.au", "gov.au", "org.au", "edu.au", "net.au",
    "co.nz", "govt.nz", "org.nz",
    "co.za", "org.za", "gov.za",
    "co.jp", "or.jp", "go.jp",
    "com.br", "gov.br", "org.br",
    "co.in", "gov.in", "org.in",
    "com.sg", "gov.sg",
    "gob.mx", "com.mx",
})


#: Suffixes with ONE registrant behind every name under them — the state. `assets.publishing.
#: service.gov.uk` and `www.gov.uk` are the same publisher, so these collapse to the suffix
#: itself. `co.uk` and `ac.uk` do NOT: `acme.co.uk` and `rival.co.uk` are two companies, and
#: `ox.ac.uk` and `cam.ac.uk` are two universities.
_STATE_SUFFIXES: frozenset[str] = frozenset({
    "gov.uk", "nhs.uk", "police.uk", "gov.au", "govt.nz", "gov.za", "go.jp", "gov.br",
    "gov.in", "gov.sg",
})


def registrable(host: str) -> str:
    """The PUBLISHER, not the hostname: `assets.publishing.service.gov.uk` -> `gov.uk`.

    Counting hostnames would let a site corroborate itself from a second subdomain, which is
    the exact failure this gate exists to reject. `host_of` first if you have a URL.
    """
    if not host:
        return ""
    parts = host.split(".")
    last_two = ".".join(parts[-2:])
    if last_two in _STATE_SUFFIXES:
        return last_two
    if len(parts) <= 2:
        return host
    if last_two in _TWO_LABEL_SUFFIXES:
        return ".".join(parts[-3:])
    return last_two


def publishers(urls: Iterable[str]) -> set[str]:
    """The distinct registrable domains behind these URLs (empty strings dropped)."""
    out = {registrable(host_of(u)) for u in urls}
    out.discard("")
    return out


def corroboration_reason(check_name: str, urls: Iterable[str], min_domains: int = 2,
                         exempt_tiers: Iterable[str] = CORROBORATION_EXEMPT_TIERS,
                         ) -> Optional[str]:
    """A sentence naming the failure, or None if the ruling stands.

    Returns None — the gate is OFF — when `min_domains <= 1`, so the whole thing is
    reversible by config alone, like `policy: off` above. An uncited ruling is not this
    gate's business either; `source_or_die` already handles it.
    """
    if min_domains <= 1:
        return None
    urls = [u for u in urls if u]
    if not urls:
        return None
    exempt = frozenset(exempt_tiers or ())
    if any(tier(h) in exempt for h in (host_of(u) for u in urls) if h):
        return None
    doms = publishers(urls)
    if not doms or len(doms) >= min_domains:
        return None
    return (f"Ruling demoted to unverifiable: every citation comes from one publisher "
            f"({', '.join(sorted(doms))}), and '{check_name}' needs {min_domains} "
            "independent publishers. Pages from one site are one source, however many "
            "of them there are.")


def demotion_reason(check_name: str, urls: Iterable[str],
                    policy: str = "P1_check_aware") -> Optional[str]:
    """A human sentence for the rationale/audit trail, or None if the ruling stands."""
    if is_ruling_admissible(check_name, urls, policy):
        return None
    hosts = sorted({h for h in (host_of(u) for u in urls) if h})
    tiers = sorted({tier(h) for h in hosts})
    return (f"Ruling demoted to unverifiable: every citation is {'/'.join(tiers)} "
            f"({', '.join(hosts)}), which cannot solely establish '{check_name}' "
            f"under admissibility policy {policy}.")
