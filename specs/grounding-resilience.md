# Spec: Grounding Resilience — Circuit Breaker + Tavily Provider

## Problem

All three search providers are simultaneously down (Exa credits, Brave unconfigured,
Gemini quota) and the daemon silently converts infrastructure failures into DEFERs,
burning LLM credits on generation with no path to verification. The daemon cannot
distinguish "zero search results" from "search infrastructure dead."

## Fixes (4 parts)

### 1. TavilySearchProvider
Add a real web-search provider via Tavily API (api.tavily.com). Simple REST call,
returns real URLs with content snippets. Clean implementation matching the
ExaSearchProvider pattern.

API: POST https://api.tavily.com/search
Key: TAVILY_API_KEY env var (free tier: 1,000 queries/month)
Response: {"results": [{"url":..., "title":..., "content":...}]}

### 2. GroundingInfrastructureError
New exception class. Raised when a provider fails for infrastructure reasons
(402/401/429/auth/network), NOT when it returns zero results. The daemon catches
this and halts immediately — refuses to burn LLM credits when grounding is dead.

### 3. Startup sanity check
Before the daemon generates a single candidate, it performs a dummy search.
If the search fails, the daemon exits with a clear error message instead of
silently looping DEFERs.

### 4. Wire Tavily into provider chain
config.yaml: provider: [tavily, exa, brave]
Tavily first (free tier, most likely working), then Exa (when topped up), then Brave.

## Acceptance criteria
1. Tavily search returns real URLs and content
2. GroundingInfrastructureError raised on 402/401/429
3. Daemon exits cleanly if startup search fails
4. Single-candidate vet produces verdicts (not all DEFER)
5. 406 existing tests still pass
