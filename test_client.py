import asyncio, os, sys, threading, websockets


async def main(url):
    loop = asyncio.get_running_loop()
    lines = asyncio.Queue()

    def read_stdin():
        while True:
            try:
                line = input()
            except EOFError:
                line = None
            loop.call_soon_threadsafe(lines.put_nowait, line)
            if line is None:
                return

    threading.Thread(target=read_stdin, daemon=True).start()

    async with websockets.connect(url) as ws:
        async def reader():
            try:
                async for msg in ws:
                    print(msg, end="", flush=True)
            except websockets.ConnectionClosed:
                pass

        task = asyncio.create_task(reader())
        while not task.done():
            getter = asyncio.create_task(lines.get())
            done, _ = await asyncio.wait({getter, task},
                                         return_when=asyncio.FIRST_COMPLETED)
            if getter not in done:
                getter.cancel()
                break
            line = getter.result()
            if line is None:
                break
            try:
                await ws.send(line)
            except websockets.ConnectionClosed:
                break
        await asyncio.sleep(0.2)


try:
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000/ws"))
except KeyboardInterrupt:
    pass
sys.stdout.flush()
os._exit(0)