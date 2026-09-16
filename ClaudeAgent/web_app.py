"""
web_app.py

Local web demo for the NASDAQ financial data-quality agent. Streams the
same trace events that agent.py prints to the terminal, but over
Server-Sent Events, to a browser UI.

Run:
    pip install fastapi uvicorn
    uvicorn web_app:app --reload
Then open http://localhost:8000

Note: this is a LOCAL demo server. It authenticates through the same
Claude Code login as the CLI (your Claude Pro/Max/etc subscription) --
it is not meant to be exposed to the internet or run on a machine
without that login.
"""

import json
import sys

if sys.platform == "win32":
    # The Claude Agent SDK spawns the CLI as a subprocess. Windows only
    # supports asyncio subprocesses on the Proactor event loop -- the
    # Selector loop (which some ASGI setups end up using) fails subprocess
    # creation, surfacing as an opaque "Failed to start Claude Code" error
    # even though the exact same call works fine in a plain script.
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse

from agent import investigate_events

app = FastAPI(title="NASDAQ Data-Quality Agent Demo")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/investigate")
async def api_investigate(
    ticker: str = Query(...),
    fiscal_year: int = Query(...),
    fiscal_period: str = Query(...),
):
    async def event_stream():
        async for event in investigate_events(ticker, fiscal_year, fiscal_period):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering if ever run behind one
        },
    )
