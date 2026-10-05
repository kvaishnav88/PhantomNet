import json, os, sqlite3, threading

_lock = threading.Lock()
_db = sqlite3.connect(os.getenv("DB_PATH", "phantomnet.db"), check_same_thread=False)
_db.execute("CREATE TABLE IF NOT EXISTS events "
            "(id INTEGER PRIMARY KEY, sid TEXT, ts REAL, type TEXT, data TEXT)")
_db.execute("CREATE INDEX IF NOT EXISTS ev_sid ON events(sid)")
_db.commit()

KEEP = {"session_start", "session_end", "command", "analysis"}


def save(ev):
    if ev.get("type") not in KEEP:
        return
    with _lock:
        _db.execute("INSERT INTO events(sid, ts, type, data) VALUES (?,?,?,?)",
                    (ev["sid"], ev["ts"], ev["type"], json.dumps(ev)))
        _db.commit()


def session(sid):
    with _lock:
        rows = _db.execute("SELECT data FROM events WHERE sid=? ORDER BY id", (sid,)).fetchall()
    return [json.loads(r[0]) for r in rows]