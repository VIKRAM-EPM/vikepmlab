"""
diagnose.py - run this once to isolate which ClaudeAgentOptions field
breaks CLI startup on this machine. Prints a clear PASS/FAIL per step.
"""
import asyncio
import os
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

CLI_PATH = os.environ.get("CLAUDE_CLI_PATH") or None


async def try_options(label, **kwargs):
    print(f"\n--- {label} ---")
    try:
        options = ClaudeAgentOptions(cli_path=CLI_PATH, max_turns=1, **kwargs)
        async with ClaudeSDKClient(options=options) as client:
            await client.query("say hi")
            async for m in client.receive_response():
                pass
        print(f"PASS: {label}")
    except Exception as e:
        print(f"FAIL: {label} -> {type(e).__name__}: {e}")


async def main():
    await try_options("baseline (cli_path only)")
    await try_options("with system_prompt", system_prompt="You are a helpful assistant.")
    await try_options("with allowed_tools (built-in only)", allowed_tools=["Read"])
    from tools import ALLOWED_TOOLS, build_server
    server = build_server()
    await try_options("with mcp_servers (our custom tools)", mcp_servers={"nasdaq-quality-tools": server})
    await try_options("with mcp_servers + allowed_tools (our custom tools)",
                       mcp_servers={"nasdaq-quality-tools": server}, allowed_tools=ALLOWED_TOOLS)


asyncio.run(main())
