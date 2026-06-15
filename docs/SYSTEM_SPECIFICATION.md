# SYSTEM SPECIFICATION: PROSPECTOR ENGINE

## 1. Core Objective
Build a grounded business-opportunity vetting engine that prioritizes **truth over creativity**. The system must ensure that no business idea is published unless it survives a six-stage evidence-based filter.

## 2. Architectural Invariants (The Non-Negotiables)
- **Source-or-Die**: Every claim must have a retrievable source. No unsourced numbers.
- **Verdict-from-Retrieval-Only**: The model rules only on fetched passages. Silence = `unverifiable`.
- **The Moat**: The verification loop (Claude/Gemini) must remain strictly isolated from the generation loop (DeepSeek/MiniMax).
- **Exit Code Zero**: A milestone is only "Complete" when the test suite returns `0`.

## 3. Execution Blueprint (The Goal Chain)
When executing a long-running build, the agent must follow this sequence:
1. **Analysis**: Read this specification and the current codebase.
2. **Goal Initialization**: Use `create_goal` to map the project into 5-10 distinct, verifiable milestones.
3. **Sequential Implementation**:
    - Implement one milestone.
    - Run relevant tests.
    - `update_goal` to mark progress.
    - Commit code only after verification.
4. **Verification**: Run `pytest` or the local compiler. Fix errors in a tight corrective loop before proceeding.

## 4. Technical Requirements
- **Language**: Python 3.11+
- **Core Pipeline**: Generate $\rightarrow$ Dedup $\rightarrow$ Pre-screen $\rightarrow$ Verify (The Moat) $\rightarrow$ Gate $\rightarrow$ Artifacts $\rightarrow$ Publish.
- **Data Store**: Local JSON dossiers and SQLite index in `store/`.
- **Failover**: Implement circuit breakers and `DEFER` logic for API outages.

## 5. Acceptance Criteria
- Successful discrimination of the Golden Set (regression tests).
- Zero "hallucinated" citations in the final dossiers.
- Full failover chain functionality (Gemini $\rightarrow$ Claude).
