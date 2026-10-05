import asyncio, sys, websockets


async def main(url):
    async with websockets.connect(url) as ws:
        async def reader():
            try:
                async for msg in ws:
                    print(msg, end="", flush=True)
            except websockets.ConnectionClosed:
                pass
        task = asyncio.create_task(reader())
        loop = asyncio.get_running_loop()
        while not task.done():
            try:
                line = await asyncio.wait_for(loop.run_in_executor(None, input), 0.2)
            except asyncio.TimeoutError:
                continue
            except EOFError:
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