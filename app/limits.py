import os, threading
from collections import defaultdict, deque
from datetime import date
import time

MAX_SESSIONS_PER_IP = 2
MAX_CONNECTS_PER_MIN = 6
MAX_CMDS_PER_MIN = 20
MAX_SESSION_SECONDS = 600
IDLE_SECONDS = 120
DAILY_LLM_BUDGET = int(os.getenv("DAILY_LLM_BUDGET", "500"))


class BudgetExceeded(Exception):
    pass


class DailyBudget:
    def __init__(self, limit):
        self.limit, self.used, self.day = limit, 0, date.today()
        self.lock = threading.Lock()

    def spend(self) -> bool:
        with self.lock:
            today = date.today()
            if today != self.day:
                self.day, self.used = today, 0
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


class BudgetedProvider:
    """Wraps an LLMProvider; refuses to call the LLM once the daily budget is spent."""

    def __init__(self, inner, budget):
        self.inner, self.budget = inner, budget

    def stream(self, system, user, max_tokens=400):
        if not self.budget.spend():
            raise BudgetExceeded()
        yield from self.inner.stream(system, user, max_tokens)


class Limiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = defaultdict(int)
        self.connects = defaultdict(deque)
        self.cmds = defaultdict(deque)

    @staticmethod
    def _hit(dq, limit, window=60):
        now = time.monotonic()
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True

    def open(self, ip):
        """Returns None if allowed, otherwise a refusal message."""
        with self.lock:
            if self.active[ip] >= MAX_SESSIONS_PER_IP:
                return "Too many open sessions from your address."
            if not self._hit(self.connects[ip], MAX_CONNECTS_PER_MIN):
                return "Too many connection attempts. Try again in a minute."
            self.active[ip] += 1
            return None

    def close(self, ip):
        with self.lock:
            self.active[ip] -= 1
            if self.active[ip] <= 0:
                del self.active[ip]

    def allow_command(self, ip):
        with self.lock:
            return self._hit(self.cmds[ip], MAX_CMDS_PER_MIN)