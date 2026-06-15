# Pi Agent Autonomous Workflow

This project leverages the Pi Agent extension ecosystem to enable asynchronous, task-chaining autonomy. Instead of manual step-by-step prompting, the agent can operate as a background manager using a "Walk-Away" blueprint.

## 1. Required Extensions
To enable autonomous goal tracking and background execution, install the following Pi packages:

```bash
# Adds long-running multi-stage goal tracking tools to Pi's memory
pi install npm:pi-codex-goal

# Allows Pi to spawn short-lived asynchronous background processes (sprints)
pi install npm:pi-side-agents
```

### Tool Capabilities:
- **`pi-codex-goal`**: Provides `create_goal`, `update_goal`, and `get_goal`. This allows the agent to programmatically break down a massive task into a checkpoint list and track progress across files.
- **`pi-side-agents`**: Enables sandboxed, concurrent background tasks that update execution progress in the terminal status line without blocking the main prompt.

## 2. The "Walk-Away" Blueprint
Follow this multi-stage process to transition from manual guidance to autonomous execution.

### Step 1: Define the Master Rails
Place a complete specification file in the repository at `docs/SYSTEM_SPECIFICATION.md`. This serves as the "Source of Truth" for all autonomous goals.

### Step 2: Set Global Boundaries
Ensure the `AGENTS.md` (or equivalent context file) explicitly points to the specification:
```markdown
# Core Directives
- Read docs/SYSTEM_SPECIFICATION.md before executing any coding goals.
- Always implement logic sequentially, building and verifying tests for each milestone before marking a step as complete.
```

### Step 3: Launch the Autonomous Chain
Launch a headless, background session by passing the master prompt via the shell using the `-p` flag:

```bash
pi -p "Analyze docs/SYSTEM_SPECIFICATION.md. Initialize a long-running goal chain to build out the database models and API endpoints sequentially. Run the test framework at every milestone, auto-commit the passing code, and do not stop until the core scaffolding matches the document."
```

## 3. Execution Lifecycle
The agent follows an iterative loop to prevent token limits and context drift:
1. **Read Master Spec** $\rightarrow$ Call `create_goal` (Map distinct sub-milestones).
2. **Loop Through Milestones** $\rightarrow$ Execute surgical edits $\rightarrow$ Run local bash tests $\rightarrow$ Update progress checklist $\rightarrow$ Commit clean state.
3. **Verification** $\rightarrow$ A task is only complete when the local testing environment returns an exit code of `0`.

Upon return, the result is a clean Git commit ledger mapping each individual component built, checked, and verified against the blueprint.
