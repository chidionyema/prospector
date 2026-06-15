// E25 Discovery Layer — 3a guided requests (WR-031). Pure mapping between the read-only guided-request
// taxonomy (goals + worked examples) and what the composer needs: the editable free-text fields it
// pre-fills, and the structured `brief_structured` tag it posts. Kept side-effect free so the mapping
// is unit-testable and the page component stays a thin shell.
//
// Invariant: `brief_structured` is demand-side intent ONLY — a goal id plus optional category hints. It
// never carries a target's name (personas are descriptions) and is never a supply map (E20 firewall).
import type { BriefStructured, RequestExample, RequestGoal } from './api/types';

/** The subset of compose fields a worked example pre-fills. The buyer edits all of them before funding. */
export interface GuidedComposeFields {
  target_persona: string;
  introduction_context: string;
  target_industry: string;
  target_seniority: string;
  meeting_objective: string;
}

/** Map a worked example onto the editable composer fields. Optional/absent fields become empty strings. */
export function composeFieldsFromExample(example: RequestExample): GuidedComposeFields {
  return {
    target_persona: example.target_persona,
    introduction_context: example.introduction_context,
    target_industry: example.target_industry ?? '',
    target_seniority: example.target_seniority ?? '',
    meeting_objective: example.meeting_objective ?? '',
  };
}

/** The structured tag for a post started from a worked example: goal + template id + category hints. */
export function briefFromExample(goal: RequestGoal, example: RequestExample): BriefStructured {
  return {
    goal: goal.id,
    template_id: example.id,
    sector: example.target_industry ?? undefined,
    seniority: example.target_seniority ?? undefined,
  };
}

/** The structured tag for a post started from a goal but written from scratch: just the goal id. */
export function briefFromGoal(goal: RequestGoal): BriefStructured {
  return { goal: goal.id };
}
