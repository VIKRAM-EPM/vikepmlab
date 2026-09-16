# NASDAQ Financial Data-Quality Agent

An agentic Claude application that investigates data-quality issues in SEC
EDGAR-derived NASDAQ fundamentals (10-K/10-Q data, 2023-2027, 2,600+
companies) and produces a judged, human-reviewable verdict rather than a
mechanical pass/fail.

## Why this is an *agent*, not a script

A validation script would apply the same fixed rule to every row: e.g.
"flag any balance-sheet mismatch >1%." That's wrong more often than it's
right in this dataset -- 17% of checkable rows fail that test, and many
are legitimate (SPACs routinely carry negative equity; biotechs have
genuinely lumpy revenue from milestone payments).

Instead, Claude is given four investigative tools and a fifth tool to
record its conclusion, and *decides itself*, at runtime, which tools to
call, in what order, and when it has enough evidence -- based on what
each tool call returns, not on hardcoded control flow. The reasoning
trace (see `agent.py`'s `_print_trace`) shows this decision-making
directly: you can watch it check a balance sheet, see a mismatch, decide
on its own to pull the company's history, and revise or confirm its
conclusion based on what it finds there.

## Architecture

```
data_access.py   Pure pandas functions -- no Claude/API dependency.
                 Independently testable ground truth. Run directly:
                     python data_access.py

tools.py         Wraps data_access functions as Claude Agent SDK
                 custom tools (in-process MCP server). This is what
                 Claude actually calls.

agent.py         Orchestration: system prompt, tool wiring, and the
                 CLI entry point. Prints a full reasoning + tool-call
                 trace so the decision path is visible, not just the
                 final answer.
```

## Setup

```bash
pip install claude-agent-sdk pandas
```

Requires Claude Code installed and logged in with a Claude subscription
(Pro/Max/Team/Enterprise) -- this script authenticates through that
login, so no separate API key or billing is needed for a project this
size. See https://code.claude.com/docs/en/quickstart for install
instructions.

## Usage

```bash
# Investigate a single ticker/period
python agent.py ABUS 2026 Q1

# Run a small fixed set of known interesting cases
python agent.py --eval

# Sanity-check the underlying data functions with no LLM involved
python data_access.py
```

## Web demo (local only)

`web_app.py` and `static/index.html` add a browser UI that streams the
same reasoning/tool-call trace live via Server-Sent Events, driven by
the exact same `investigate_events()` generator the CLI uses -- no
duplicated logic.

```bash
pip install fastapi uvicorn
uvicorn web_app:app --reload
```

Then open http://localhost:8000, pick a ticker (or one of the "known
interesting cases" quick-pick buttons), and watch the trace populate
live.

This is a **local-only** demo: it authenticates through the same
Claude Code login as the CLI. It is not meant to be deployed publicly
or run on a machine without that subscription login (e.g. a locked-down
work laptop) -- for that scenario, see the static, no-install replay
page built from a real captured run instead.

## Known interesting cases (found during dataset exploration)

| Ticker | Period | Why it's interesting |
|---|---|---|
| AACI | 2026 Q2 | SPAC with ~$251M balance-sheet "mismatch" -- actually a trust-liability structure, not an error |
| ABUS | 2026 Q1 | Revenue jumps 338x quarter-over-quarter alongside a matching net-income and equity jump -- looks like a data error but is very likely a real one-time event (litigation/licensing) |
| AGNC | 2025 Q1 | REIT with negative revenue figures and large swings -- normal for the business model, not a parsing error |

These are deliberately chosen because a naive rule-based validator gets
all three wrong in one direction or the other.

## Mapping to agentic AI / solution delivery skills

- **Agent orchestration & tool calling** -- `tools.py` + `agent.py`
- **MCP server implementation** -- `create_sdk_mcp_server` in `tools.py` (in-process MCP server)
- **Structured outputs** -- the `propose_verdict` tool's schema
- **Human review where appropriate** -- `propose_verdict` only records a recommendation; nothing is auto-applied
- **Agent evaluations / regression testing** -- `EVAL_CASES` in `agent.py`; extend with more known cases over time
- **Data modeling & backend engineering** -- `data_access.py`

## Not yet built (natural next steps)

- Automated eval assertions (currently the eval cases print a trace for
  manual review, since the whole point is these require judgment --
  could add a second Claude call that grades the trace against
  documented expected reasoning)
- A RAG layer over SEC filing definitions so the agent can cite *why*
  a metric is defined the way it is
- Persisting `propose_verdict` output to a real review queue/DB instead
  of printing it
