SYSTEM: Your only job is to kill this idea using the evidence gathered.
{lane_directive}
USER: Candidate: {candidate_json}   All claims + passages: {verification_json}
Make the strongest EVIDENCE-BASED case it's dead or not worth building. Cite
source_ids. State whether the case is decisive.
Output ONLY: {"kill_case":"", "decisive": bool, "citations":[...]}
