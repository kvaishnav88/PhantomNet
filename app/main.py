import asyncio, logging, os, re, secrets, time
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app import store
from app.llm import get_provider
from app.cache import Session, USER, HOME
from app.shell import run_command, make_system
from app.lore import LORE
from app.events import Hub
from app.analyst import analyze
from app.sqlmock import DB as PG_DB
from app.limits import (Limiter, DailyBudget, BudgetedProvider, BudgetExceeded,
                        DAILY_LLM_BUDGET, MAX_SESSION_SECONDS, IDLE_SECONDS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("phantomnet")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)
limiter = Limiter()
budget = DailyBudget(DAILY_LLM_BUDGET)
raw_provider = get_provider()
provider = BudgetedProvider(raw_provider, budget)
hub = Hub()
bg_tasks = set()
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")

BUSY = "bash: fork: retry: Resource temporarily unavailable\n"


@app.get("/health")
def health():
    return {"status": "ok", "llm_calls_today": budget.used, **hub.stats}


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    if not re.fullmatch(r"[0-9a-f]{6,12}", sid):
        raise HTTPException(404)
    events = store.session(sid)
    if not events:
        raise HTTPException(404)
    return {"sid": sid, "events": events}


def client_ip(ws: WebSocket) -> str:
    h = ws.headers
    for name in ("true-client-ip", "cf-connecting-ip"):
        if h.get(name):
            return h[name].strip()
    fwd = h.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"

def prompt(session) -> str:
    if session.psql:
        return f"{PG_DB}{'->' if session.psql.buf else '=>'} "
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


async def run_analysis(sid, cmds):
    result = await analyze(cmds, raw_provider, budget)
    hub.publish({"type": "analysis", "sid": sid, "n": len(cmds), **result})


def schedule_analysis(sid, cmds):
    task = asyncio.create_task(run_analysis(sid, list(cmds)))
    bg_tasks.add(task)
    task.add_done_callback(bg_tasks.discard)


@app.websocket("/monitor")
async def monitor(ws: WebSocket):
    await ws.accept()
    if DASHBOARD_TOKEN and ws.query_params.get("token") != DASHBOARD_TOKEN:
        await ws.close(code=1008)
        return
    q = hub.subscribe()
    if q is None:
        await ws.close(code=1013)
        return
    recv = asyncio.create_task(ws.receive_text())
    recv.add_done_callback(lambda t: t.cancelled() or t.exception())
    get = None
    try:
        for ev in list(hub.log):
            await ws.send_json(ev)
        await ws.send_json(hub.stats_event())
        while True:
            if get is None:
                get = asyncio.create_task(q.get())
            done, _ = await asyncio.wait({recv, get}, timeout=25,
                                         return_when=asyncio.FIRST_COMPLETED)
            if recv in done:
                break
            if get in done:
                await ws.send_json(get.result())
                get = None
            else:
                await ws.send_json({"type": "ping"})
    except Exception:
        pass
    finally:
        hub.unsubscribe(q)
        recv.cancel()
        if get is not None:
            get.cancel()
        try:
            await ws.close()
        except Exception:
            pass


@app.websocket("/ws")
async def shell(ws: WebSocket):
    ip = client_ip(ws)
    log.info("HDRS tci=%s cfip=%s xff=%s sock=%s", ws.headers.get("true-client-ip"),
        ws.headers.get("cf-connecting-ip"), ws.headers.get("x-forwarded-for"),
        ws.client.host if ws.client else None)
    await ws.accept()
    refusal = limiter.open(ip)
    if refusal:
        await ws.send_text(refusal + "\n")
        await ws.close(code=1013)
        return

    session, system = Session(), make_system()
    sid = secrets.token_hex(5)
    cmds = []
    deadline = time.monotonic() + MAX_SESSION_SECONDS
    log.info("connect sid=%s ip=%s", sid, ip)
    hub.session_started(sid, ip)
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
            if line in ("exit", "logout") and not session.psql:
                await ws.send_text("logout\n")
                break
            if not line:
                continue
            log.info("cmd sid=%s ip=%s %r", sid, ip, line)
            if not limiter.allow_command(ip):
                await ws.send_text(BUSY)
                continue

            before = budget.used
            psql_related = session.psql is not None or line.split()[0] == "psql"
            start, first, out = time.perf_counter(), None, []
            try:
                async for chunk in iterate(run_command(session, line, provider, system)):
                    if first is None:
                        first = (time.perf_counter() - start) * 1000
                    out.append(chunk)
                    await ws.send_text(chunk)
            except BudgetExceeded:
                out.append(BUSY)
                await ws.send_text(BUSY)
            except WebSocketDisconnect:
                raise
            except Exception:
                log.exception("command failed")
                out.append(BUSY)
                await ws.send_text(BUSY)

            used_llm = budget.used > before
            hub.command(sid, line, "".join(out), used_llm,
                        first if used_llm and not psql_related else None)
            cmds.append(line)
            if len(cmds) % 5 == 0:
                schedule_analysis(sid, cmds)
    except WebSocketDisconnect:
        pass
    finally:
        limiter.close(ip)
        if len(cmds) >= 2 and len(cmds) % 5 != 0:
            schedule_analysis(sid, cmds)
        hub.session_ended(sid)
        log.info("disconnect sid=%s ip=%s", sid, ip)
        try:
            await ws.close()
        except Exception:
            pass