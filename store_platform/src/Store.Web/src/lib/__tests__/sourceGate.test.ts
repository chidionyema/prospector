import { describe, expect, it } from "vitest";
import {
  gateCheck,
  gateSource,
  isSlugTitle,
  jurisdictionMatches,
  pickPassedSampleCheck,
  thinEvidenceLabel,
} from "../sourceGate";

/** The six sources that shipped on the homepage sample payer check, 2026-09-02. */
const LIVE_PAYER = [
  {
    url: "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/adhocs/2511annualsurveyofhoursandearningsasheestimatesofgrossbasicweeklyandannualearningsforspecifiedoccupationsengland2023and2024",
    domain: "ons.gov.uk",
    label: "",
  },
  {
    url: "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/earningsandhoursworkedbyindustryandoccupationashetable29",
    domain: "ons.gov.uk",
    label: "",
  },
  {
    url: "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/adhocs/3139annualsurveyofhoursandearningsasheestimatesofgrossbasicweeklyandannualearningsforspecifiedoccupationsengland2024and2025",
    domain: "ons.gov.uk",
    label: "",
  },
  {
    url: "https://www.latitudefinancial.com.au/hardship-care/",
    domain: "latitudefinancial.com.au",
    label: "",
  },
  {
    url: "https://www.reachlink.com/advice/stress/what-gig-work-actually-does-to-your-sense-of-self/",
    domain: "reachlink.com",
    label: "",
  },
  {
    url: "https://www.consumeraffairs.com/finance/hardship-loans.html",
    domain: "consumeraffairs.com",
    label: "",
  },
];

describe("isSlugTitle", () => {
  it("rejects the live ONS adhoc slug", () => {
    expect(
      isSlugTitle(
        "3139annualsurveyofhoursandearningsasheestimatesofgrossbasicweeklyandannualearningsforspecifiedoccupationsengland2024and2025",
      ),
    ).toBe(true);
  });
  it("keeps a human title", () => {
    expect(isSlugTitle("Annual Survey of Hours and Earnings")).toBe(false);
  });
});

describe("jurisdictionMatches", () => {
  it("keeps ons.gov.uk on a UK pack and drops AU/US loan sites", () => {
    expect(jurisdictionMatches("ons.gov.uk", "UK")).toBe(true);
    expect(jurisdictionMatches("latitudefinancial.com.au", "UK")).toBe(false);
    expect(jurisdictionMatches("consumeraffairs.com", "UK")).toBe(false);
  });
  it("allows ISO from any market", () => {
    expect(jurisdictionMatches("iso.org", "UK")).toBe(true);
    expect(jurisdictionMatches("iso.org", "US")).toBe(true);
  });
});

describe("gateSource", () => {
  it("fails the live ONS rows as slug titles", () => {
    const r = gateSource(LIVE_PAYER[2], { market: "UK", claim: true });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("slug-title");
  });
  it("fails a cookie-consent body even with a real title", () => {
    const r = gateSource(
      {
        url: "https://www.ons.gov.uk/peopleinwork",
        domain: "ons.gov.uk",
        label: "Earnings in England",
      },
      { market: "UK", claim: true, fetchedText: "We use cookies. Accept all cookies to continue." },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("junk-content");
  });
  it("keeps a UK source with a title, content, and a claim", () => {
    const r = gateSource(
      {
        url: "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork",
        domain: "ons.gov.uk",
        label: "Earnings and working hours",
        excerpt: "Median weekly pay for full-time employees was £728 in April 2024.",
      },
      { market: "UK", claim: true },
    );
    expect(r).toEqual({ ok: true, title: "Earnings and working hours" });
  });
  it("fails a source that is not cited against a claim", () => {
    const r = gateSource(
      {
        url: "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork",
        domain: "ons.gov.uk",
        label: "Earnings and working hours",
        excerpt: "Median weekly pay for full-time employees was £728 in April 2024.",
      },
      { market: "UK", claim: false },
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("no-claim");
  });
});

describe("gateCheck", () => {
  it("marks the live homepage payer check as evidence thin", () => {
    const out = gateCheck({
      sources: LIVE_PAYER,
      market: "UK",
      hasClaim: true,
      fetchedTextByUrl: {
        [LIVE_PAYER[0].url]: "This website uses cookies. Please accept to continue.",
        [LIVE_PAYER[1].url]: "Enable JavaScript to view this page.",
      },
    });
    expect(out.kept).toEqual([]);
    expect(out.thin).toBe(true);
    expect(thinEvidenceLabel(out.count)).toBe("Evidence thin · 0 sources");
  });
});


describe("pickPassedSampleCheck", () => {
  it("skips the live unverifiable payer check and takes a passed one with real sources", () => {
    const picked = pickPassedSampleCheck(
      [
        {
          name: "Can the buyer pay?",
          verdict: "unverifiable",
          rationale: "Cookie banners only.",
          sources: LIVE_PAYER,
        },
        {
          name: "Is the pain real?",
          verdict: "supported",
          rationale: "UK tribunal cases name the same deactivation harm.",
          sources: [
            {
              url: "https://www.acas.org.uk/dismissal",
              domain: "acas.org.uk",
              label: "Dismissal and grievance",
              excerpt: "A worker can challenge an unfair dismissal at a tribunal.",
            },
            {
              url: "https://www.gov.uk/employment-tribunals",
              domain: "gov.uk",
              label: "Employment tribunals",
              excerpt: "You can make a claim to an employment tribunal.",
            },
            {
              url: "https://iwgb.org.uk/en/page/support-and-advice/",
              domain: "iwgb.org.uk",
              label: "Support and advice",
              excerpt: "The union represents gig workers in dismissal cases.",
            },
          ],
        },
      ],
      "UK",
    );
    expect(picked?.name).toBe("Is the pain real?");
    expect(picked?.sources).toHaveLength(3);
  });
});
