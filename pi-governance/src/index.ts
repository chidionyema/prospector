import { PiExtension, SessionContext, AgentResponse } from '@mariozechner/pi-coding-agent';

/**
 * PI-GOVERNANCE: Global Operational DNA
 * This extension enforces the four pillars across all projects.
 */
export class PiGovernanceExtension extends PiExtension {
  
  private readonly GLOBAL_DIRECTIVES = `
# GLOBAL OPERATING DIRECTIVE: THE CORE DNA
You are operating under a strict Governance Framework. These rules override all others.

## PILLAR 1: EPISTEMIC HUMILITY
- Only make changes that are directly requested. No unsolicited refactoring.
- If a detail is not in your current context window, you DO NOT know it. Search, don't guess.
- Pausing to verify is zero-cost; autonomous error is catastrophic.

## PILLAR 2: SEMANTIC TOOL PRIORITIZATION
- Prefer semantic file tools over raw shell commands.
- NO 'sed', 'awk', or 'cat > file' for code mutation. Use structured find-and-replace.
- Use 'grep' for reconnaissance; keep context clean.

## PILLAR 3: PERCEPTION-PLANNING-EXECUTION (P-P-E)
Every task MUST follow this sequence:
1. PERCEPTION: Map touchpoints and read specific modules.
2. PLANNING: State exactly what you will do. Read-only until the plan is set.
3. EXECUTION: Mutate minimum required lines.
4. VALIDATION: Run tests. Read the terminal output.

## PILLAR 4: CLOSED-LOOP SELF-HEALING (EXIT CODE ZERO)
- A task is NOT complete until the local test/compiler returns exit code 0.
- Treat stderr as absolute truth. Stop and self-heal in a tight loop.

## OPERATIONAL REQUIREMENTS:
- For any task involving >3 steps, you MUST use 'create_goal' to initialize a goal chain.
- Every turn must start with a <thinking> block processing state and dependencies.
- No conversational fluff. Act as a high-efficiency terminal utility.
`;

  /**
   * Hook into the start of every session to inject the DNA.
   */
  async onSessionStart(context: SessionContext): Promise<void> {
    console.log('[pi-governance] Injecting Global Operational DNA...');
    
    // We inject the directives into the system prompt.
    // This ensures the behavior travels across any project.
    await context.injectSystemPrompt(this.GLOBAL_DIRECTIVES);
  }

  /**
   * Intercept tool calls to enforce goal tracking.
   */
  async onBeforeToolCall(toolName: string, args: any, context: SessionContext): Promise<void> {
    // If the agent is about to edit a file but hasn't created a goal for the current session,
    // we provide a system-level nudge.
    if (toolName === 'edit' || toolName === 'write') {
      const goals = await context.getGoals();
      if (!goals || goals.length === 0) {
        // This is a "soft" enforcement - reminding the agent of its DNA.
        await context.injectSystemPrompt(
          "\n[GOVERNANCE WARNING]: You are mutating code without an active Goal Chain. " +
          "Refer to PILLAR 3: Initialize a goal chain via 'create_goal' before proceeding."
        );
      }
    }
  }

  /**
   * Post-action verification.
   */
  async onAfterToolCall(toolName: string, response: AgentResponse, context: SessionContext): Promise<void> {
    if (toolName === 'edit' || toolName === 'write') {
      // Force the agent to think about verification after every mutation.
      await context.injectSystemPrompt(
        "\n[GOVERNANCE CHECK]: Mutation complete. You MUST now execute the local test suite " +
        "to verify Exit Code Zero before declaring this step finished."
      );
    }
  }
}
