import asyncio, json, sys, websockets


async def main(url):
    async with websockets.connect(url) as ws:
        async for raw in ws:
            ev = json.loads(raw)
            t, sid = ev.get("type"), ev.get("sid", "-")
            if t == "ping":
                continue
            if t == "command":
                print(f"[{sid}] $ {ev['cmd']}  (llm={ev['llm']}, ttft={ev['ttft_ms']} ms)")
            elif t == "analysis":
                print(f"[{sid}] ANALYSIS skill={ev['skill']} goal={ev['goal']} "
                      f"risk={ev['risk']} via={ev['source']}\n      {ev['summary']}")
            elif t == "stats":
                print(f"      stats: {ev['sessions']} sessions, {ev['commands']} cmds, "
                      f"avg ttft {ev['avg_ttft_ms']} ms")
            else:
                print(f"[{sid}] {t}")

try:
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000/monitor"))
except KeyboardInterrupt:
    pass