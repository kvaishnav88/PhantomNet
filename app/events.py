import asyncio, time
from collections import deque

from app import store

MAX_MONITORS = 20


def mask_ip(ip: str) -> str:
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3] + ["x"])
    return ip[:4] + "***"


class Hub:
    """In-process event feed: sessions publish, dashboards subscribe."""

    def __init__(self):
        self.subs = set()
        self.log = deque(maxlen=200)
        self.stats = {"sessions": 0, "active": 0, "commands": 0,
                      "llm_commands": 0, "avg_ttft_ms": 0}
        self._ttft_sum = 0.0
        self._ttft_n = 0

    def subscribe(self):
        if len(self.subs) >= MAX_MONITORS:
            return None
        q = asyncio.Queue(maxsize=200)
        self.subs.add(q)
        return q

    def unsubscribe(self, q):
        self.subs.discard(q)

    def publish(self, event, keep=True):
        event["ts"] = time.time()
        if keep:
            store.save(event)
            self.log.append(event)
        for q in list(self.subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def stats_event(self):
        return {"type": "stats", **self.stats}

    def session_started(self, sid, ip):
        self.stats["sessions"] += 1
        self.stats["active"] += 1
        self.publish({"type": "session_start", "sid": sid, "ip": mask_ip(ip)})
        self.publish(self.stats_event(), keep=False)

    def session_ended(self, sid):
        self.stats["active"] = max(0, self.stats["active"] - 1)
        self.publish({"type": "session_end", "sid": sid})
        self.publish(self.stats_event(), keep=False)

    def command(self, sid, cmd, output, used_llm, ttft_ms):
        s = self.stats
        s["commands"] += 1
        if used_llm:
            s["llm_commands"] += 1
        if used_llm and ttft_ms is not None:
            self._ttft_sum += ttft_ms
            self._ttft_n += 1
            s["avg_ttft_ms"] = round(self._ttft_sum / self._ttft_n)
        self.publish({
            "type": "command", "sid": sid, "cmd": cmd[:200],
            "output": output[:4000], "truncated": len(output) > 4000,
            "llm": used_llm,
            "ttft_ms": round(ttft_ms) if ttft_ms is not None else None,
        })
        self.publish(self.stats_event(), keep=False)