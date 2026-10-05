import asyncio, logging, time
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.llm import get_provider
from app.cache import Session, USER, HOME
from app.shell import run_command, make_system
from app.lore import LORE
from app.limits import (Limiter, DailyBudget, BudgetedProvider, BudgetExceeded,
                        DAILY_LLM_BUDGET, MAX_SESSION_SECONDS, IDLE_SECONDS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("phantomnet")

app = FastAPI()
limiter = Limiter()
budget = DailyBudget(DAILY_LLM_BUDGET)
provider = BudgetedProvider(get_provider(), budget)

BUSY = "bash: fork: retry: Resource temporarily unavailable\n"


@app.get("/health")
def health():
    return {"status": "ok", "llm_calls_today": budget.used}


def client_ip(ws: WebSocket) -> str:
    fwd = ws.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return ws.client.host if ws.client else "unknown"


def prompt(session) -> str:
    cwd = "~" + session.cwd[len(HOME):] if session.cwd.startswith(HOME) else session.cwd
    return f"{USER}@{LORE['hostname']}:{cwd}$ "


def banner() -> str:
    last = datetime.now() - timedelta(days=1, hours=2)
    return ("Welcome to Ubuntu 22.04.4 LTS (GNU/Linux 5.15.0-117-generic x86_64)\n\n"
            f"Last login: {last:%a %b %d %H:%M:%S %Y} from 10.20.4.17\n")


async def iterate(gen):
    """Run a blocking generator in a worker thread, one chunk at a time."""
    loop = asyncio.get_running_loop()
    it, done = iter(gen), object()
    while True:
        chunk = await loop.run_in_executor(None, next, it, done)
        if chunk is done:
            return
        yield chunk


@app.websocket("/ws")
async def shell(ws: WebSocket):
    ip = client_ip(ws)
    await ws.accept()
    refusal = limiter.open(ip)
    if refusal:
        await ws.send_text(refusal + "\n")
        await ws.close(code=1013)
        return

    session, system = Session(), make_system()
    deadline = time.monotonic() + MAX_SESSION_SECONDS
    log.info("connect ip=%s", ip)
    try:
        await ws.send_text(banner())
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await ws.send_text("\nConnection closed by remote host.\n")
                break
            await ws.send_text(prompt(session))
            try:
                line = await asyncio.wait_for(
                    ws.receive_text(), timeout=min(remaining, IDLE_SECONDS))
            except asyncio.TimeoutError:
                await ws.send_text("\nConnection closed by remote host.\n")
                break

            line = line.strip()[:200]
            if line in ("exit", "logout"):
                await ws.send_text("logout\n")
                break
            if not line:
                continue
            log.info("cmd ip=%s %r", ip, line)
            if not limiter.allow_command(ip):
                await ws.send_text(BUSY)
                continue
            try:
                async for chunk in iterate(run_command(session, line, provider, system)):
                    await ws.send_text(chunk)
            except BudgetExceeded:
                await ws.send_text(BUSY)
            except WebSocketDisconnect:
                raise
            except Exception:
                log.exception("command failed")
                await ws.send_text(BUSY)
    except WebSocketDisconnect:
        pass
    finally:
        limiter.close(ip)
        log.info("disconnect ip=%s", ip)
        try:
            await ws.close()
        except Exception:
            pass