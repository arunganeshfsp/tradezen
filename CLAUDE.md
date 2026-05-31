# TradeZen — Claude Code Instructions

## SDD Protocol

This project follows **Specification Driven Development**.

### Before starting a task — read selectively

| Situation | What to read |
|---|---|
| Working on a specific module | `agent-artifacts/context/(module).md` if status = `active` |
| Unfamiliar with the stack or a new module | `agent-artifacts/spec-kit/architecture.md` |
| Cross-module change or dependency question | `agent-artifacts/spec-kit/modules.md` |
| Simple fix within a file already read this session | Nothing — use existing context |

Never read all spec files on every prompt. Read only what the task requires.

### After completing a task — always update context

After every task that changes a module's behaviour, structure, or known issues:

1. Write or update `agent-artifacts/context/(module).md` with:
   - **What changed** — key functions added/modified, layout changes, new state
   - **Why** — the reason (bug, UX improvement, user request)
   - **Known caveats** — anything non-obvious a future agent must know
   - **Open issues** — bugs deferred, edge cases not handled
2. Update the `Status` column in `agent-artifacts/context/index.md` → `active`

This step is **mandatory**, not optional. It is how the context grows and replaces re-reading the codebase.

## Git Policy

Never run `git add`, `git commit`, or `git push`. The user handles all repository operations.

## SEBI Compliance — Language Rules

TradeZen is an **educational platform**, not a SEBI-registered Investment Adviser. All UI copy, tooltips, nudges, and AI-generated text must follow these rules:

**Never use:**
- "Buy" / "Sell" as an action directive ("buy this stock", "good time to buy")
- "Entry point" / "Exit point" as advice
- "Invest in" / "Avoid" as a recommendation
- Any phrasing that implies a trading signal or investment advice

**Always use instead:**
- "Study the session" / "Observe the setup"
- "Reference level" instead of "entry"
- "Bullish setup" / "Bearish setup" (descriptive, not directive)
- "This stock may be worth tracking" instead of "consider buying"
- Nudges must be framed as **analysis tools**, not action prompts (e.g., "See how this stock traded yesterday in Trade Player" not "find a good entry in Trade Player")

**Every tool page** that shows scores, signals, or health ratings must carry a one-line disclaimer:
> "For educational purposes only. Not investment advice. Consult a SEBI-registered adviser before trading."

This rule applies to: all HTML copy, template strings, story beats, nudge text, persona descriptions, and any user-facing text generated at runtime.

## Code Conventions

- No comments unless the WHY is non-obvious
- No trailing summaries in responses — the user can read the diff
- Prefer editing existing files over creating new ones
- No feature flags, backward-compat shims, or dead code
- Emoji only if the user explicitly asks

## Stack Quick-Reference

| Layer | Tech | Port |
|---|---|---|
| Frontend | HTML + Vanilla JS + Bootstrap 5.3 | — |
| Node proxy | Express (`server.js`) | 3000 |
| Python API | FastAPI (`ai_engine/main.py`) | 8000 |
| Launcher | Express (`launcher.js`) with basic-auth | 9999 |

All browser requests hit Node :3000. Routes under `/api/*` and `/mgmt/*` are proxied to Python :8000.
