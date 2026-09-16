"""
tools.py

Wraps the pure-Python functions in data_access.py as Claude Agent SDK
custom tools, bundled into a single in-process MCP server. This is the
layer that actually makes this an "agent" project rather than a script:
Claude decides which of these to call, in what order, based on what
each one returns.
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

import data_access as da


@tool(
    "check_balance_sheet",
    "Verify Assets = Liabilities + Equity for a specific ticker/period. "
    "Returns the raw figures and the mismatch, but does NOT decide whether "
    "a mismatch is an error -- call get_period_history to check if it's a "
    "recurring, legitimate pattern (e.g. a SPAC with negative equity) "
    "before concluding it's a data error.",
    {"ticker": str, "fiscal_year": int, "fiscal_period": str},
)
async def check_balance_sheet(args):
    result = da.check_balance_sheet(args["ticker"], args["fiscal_year"], args["fiscal_period"])
    return {"content": [{"type": "text", "text": str(result)}]}


@tool(
    "get_period_history",
    "Get a ticker's recent period-over-period financial history "
    "(revenue, net income, assets, liabilities, equity). Use this to "
    "judge whether something flagged by another tool is a one-off "
    "anomaly or a consistent, legitimate pattern for that company.",
    {"ticker": str},
)
async def get_period_history(args):
    result = da.get_period_history(args["ticker"])
    return {"content": [{"type": "text", "text": str(result)}]}


@tool(
    "check_revenue_continuity",
    "Flag large quarter-over-quarter revenue swings (default >20x or "
    "<0.05x) for a ticker. A flag is a candidate issue, not a confirmed "
    "one -- real M&A, milestone payments, or litigation settlements can "
    "produce swings this large. Cross-check with get_period_history "
    "before concluding it's a data error.",
    {"ticker": str},
)
async def check_revenue_continuity(args):
    result = da.check_revenue_continuity(args["ticker"])
    return {"content": [{"type": "text", "text": str(result)}]}


@tool(
    "check_eps_consistency",
    "Cross-check reported basic EPS against net_income / shares_outstanding "
    "for a specific ticker/period. NOTE: this dataset's shares_outstanding "
    "is a period-end figure, not the weighted-average figure basic EPS "
    "actually uses, so mismatches are common and not automatically errors.",
    {"ticker": str, "fiscal_year": int, "fiscal_period": str},
)
async def check_eps_consistency(args):
    result = da.check_eps_consistency(args["ticker"], args["fiscal_year"], args["fiscal_period"])
    return {"content": [{"type": "text", "text": str(result)}]}


@tool(
    "propose_verdict",
    "Submit your final structured assessment for this ticker/period. "
    "This does NOT apply any fix automatically -- it only records your "
    "proposed classification and reasoning for human review. Call this "
    "exactly once, after you've gathered enough evidence with the other "
    "tools.",
    {
        "ticker": str,
        "fiscal_year": int,
        "fiscal_period": str,
        "verdict": str,  # "likely_error" | "likely_legitimate" | "needs_human_review"
        "confidence": str,  # "low" | "medium" | "high"
        "reasoning": str,
        "issues_found": str,  # comma-separated short labels
    },
)
async def propose_verdict(args):
    # In a real deployment this would write to a review queue / DB.
    # For the demo, we just echo it back -- the CLI prints it as the
    # final report, and nothing is auto-applied to the dataset.
    return {"content": [{"type": "text", "text": f"Verdict recorded (pending human review): {args}"}]}


def build_server():
    return create_sdk_mcp_server(
        name="nasdaq-quality-tools",
        version="1.0.0",
        tools=[
            check_balance_sheet,
            get_period_history,
            check_revenue_continuity,
            check_eps_consistency,
            propose_verdict,
        ],
    )


ALLOWED_TOOLS = [
    "mcp__nasdaq-quality-tools__check_balance_sheet",
    "mcp__nasdaq-quality-tools__get_period_history",
    "mcp__nasdaq-quality-tools__check_revenue_continuity",
    "mcp__nasdaq-quality-tools__check_eps_consistency",
    "mcp__nasdaq-quality-tools__propose_verdict",
]
