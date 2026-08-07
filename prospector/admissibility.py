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
UGC_ADMISSIBLE = {"distribution", "route_to_market", "buyer_intent", "pain_reality"}

# Policy names. `off` is a real option, not a placeholder: it is the pre-§20 behaviour and the
# thing every measurement is stated against.
POLICIES = ("off", "P2_farm_only", "P1_check_aware", "P0_global")


def tier(host: str) -> str:
    """Classify a bare hostname. Unknown => `other` (76.4% of evidence; unaudited, NOT endorsed)."""
    if host in STATS_FARM:
        return "stats_farm"
    if host in REFERENCE_NOISE:
        return "reference_noise"
    if host in UGC_SOCIAL:
        return "ugc_social"
    if host in REGULATORS or host.endswith(GOV_SUFFIXES):
        return "government"
    if host in ACADEMIC_HOSTS or host.endswith(ACADEMIC_SUFFIXES):
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
