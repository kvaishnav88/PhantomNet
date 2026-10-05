import json, random, re, sqlite3, time, unicodedata
from datetime import date, datetime, timedelta, timezone
from app.lore import LORE

DB, USER, HOST = "hfs_prod", "svc_ops", "hfs-db-01"
VERSION = ("PostgreSQL 14.12 (Ubuntu 14.12-0ubuntu0.22.04.1) on x86_64-pc-linux-gnu, "
           "compiled by gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0, 64-bit")
MAX_ROWS = 500

TABLES = {
    "employees": [("id", "integer"), ("full_name", "text"), ("email", "text"),
                  ("department", "text"), ("title", "text"), ("hire_date", "date"),
                  ("salary", "numeric(10,2)")],
    "payroll": [("id", "integer"), ("employee_id", "integer"), ("period", "date"),
                ("gross", "numeric(10,2)"), ("tax", "numeric(10,2)"), ("net", "numeric(10,2)")],
    "customers": [("id", "integer"), ("name", "text"), ("contact_email", "text"),
                  ("country", "text"), ("credit_limit", "numeric(12,2)")],
    "shipments": [("id", "text"), ("customer_id", "integer"), ("origin", "text"),
                  ("destination", "text"), ("status", "text"), ("weight_kg", "numeric(8,2)"),
                  ("ship_date", "date")],
}
EXTRA = {
    "employees": 'Indexes:\n    "employees_pkey" PRIMARY KEY, btree (id)\n',
    "payroll": ('Indexes:\n    "payroll_pkey" PRIMARY KEY, btree (id)\n'
                'Foreign-key constraints:\n    "payroll_employee_id_fkey" FOREIGN KEY (employee_id) REFERENCES employees(id)\n'),
    "customers": 'Indexes:\n    "customers_pkey" PRIMARY KEY, btree (id)\n',
    "shipments": ('Indexes:\n    "shipments_pkey" PRIMARY KEY, btree (id)\n'
                  'Foreign-key constraints:\n    "shipments_customer_id_fkey" FOREIGN KEY (customer_id) REFERENCES customers(id)\n'),
}
EXEC_META = {
    "CEO": ("Chief Executive Officer", "Executive", 285000),
    "CTO": ("Chief Technology Officer", "Technology", 240000),
    "CFO": ("Chief Financial Officer", "Finance", 235000),
    "VP Operations": ("VP Operations", "Fleet Operations", 192000),
    "Head of Security": ("Head of Security", "Security", 164000),
}
FIRST = ["Aarav", "Sofia", "Liam", "Mei", "Carlos", "Fatima", "Jonas", "Ingrid",
         "Rahul", "Chloe", "Mateo", "Yuki", "Omar", "Hannah", "Kwame", "Lucia"]
LAST = ["Nair", "Rossi", "Becker", "Lin", "Mendes", "Haddad", "Larsen", "Novak",
        "Patel", "Dubois", "Garcia", "Tanaka", "Khalil", "Schmidt", "Mensah", "Silva"]
TITLES = ["Analyst", "Coordinator", "Engineer", "Specialist", "Manager", "Lead"]
SUFFIX = ["Logistics", "Cargo", "Trading", "Foods", "Textiles", "Motors", "Retail"]
COUNTRIES = ["Germany", "Netherlands", "Spain", "Poland", "Italy", "France", "Turkey", "Belgium"]
CITIES = ["Rotterdam, NL", "Hamburg, DE", "Antwerp, BE", "Gdansk, PL", "Valencia, ES",
          "Genoa, IT", "Le Havre, FR", "Istanbul, TR", "Lisbon, PT", "Vienna, AT"]
WRITE = {"insert", "update", "delete", "drop", "alter", "create", "truncate",
         "grant", "revoke", "copy", "vacuum", "do", "call"}
BLOCK = re.compile(r"sqlite_|pragma|attach|load_extension|zeroblob|randomblob", re.I)
SYS = "You generate fictional sample data. Reply with ONLY a JSON array, no markdown, no commentary."


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f") + "+00"


SPECIAL = {
    "select version()": ("version", lambda: VERSION),
    "select current_user": ("current_user", lambda: USER),
    "select current_database()": ("current_database", lambda: DB),
    "select now()": ("now", _now),
}


def _s(v):
    if v is None:
        return ""
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def fmt(headers, rows, title=None):
    cells = [[_s(v) for v in r] for r in rows]
    n = len(headers)
    right = [bool(rows) and all(isinstance(r[i], (int, float)) or r[i] is None for r in rows)
             and any(r[i] is not None for r in rows) for i in range(n)]
    w = [max([len(h)] + [len(c[i]) for c in cells]) for i, h in enumerate(headers)]
    out = []
    if title:
        out.append(title.center(sum(w) + 3 * n - 1).rstrip() + "\n")
    out.append("|".join(" " + h.center(w[i]) + " " for i, h in enumerate(headers)) + "\n")
    out.append("+".join("-" * (w[i] + 2) for i in range(n)) + "\n")
    for c in cells:
        parts = []
        for i in range(n):
            if right[i]:
                parts.append(" " + c[i].rjust(w[i]) + " ")
            elif i == n - 1:
                parts.append(" " + c[i])
            else:
                parts.append(" " + c[i].ljust(w[i]) + " ")
        out.append("|".join(parts).rstrip() + "\n")
    out.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})\n\n")
    return "".join(out)


def _slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", ".", s).strip(".")


def _sq(ty):
    ty = ty.split("(")[0]
    return {"integer": "INTEGER", "numeric": "REAL"}.get(ty, "TEXT")


def _colname(c):
    m = re.match(r"^(\w+)\(.*\)$", c)
    return m.group(1).lower() if m else c


def _pos(sql, tok):
    i = sql.lower().find(tok.lower())
    return "" if i < 0 else f"LINE 1: {sql}\n{' ' * (8 + i)}^\n"


def _pg_error(msg, sql=""):
    m = re.search(r'near "([^"]+)"', msg)
    if m:
        return f'ERROR:  syntax error at or near "{m.group(1)}"\n' + _pos(sql, m.group(1))
    if "incomplete input" in msg:
        return "ERROR:  syntax error at end of input\n"
    m = re.match(r"no such table: (?:\w+\.)?(\w+)", msg)
    if m:
        return f'ERROR:  relation "{m.group(1)}" does not exist\n' + _pos(sql, m.group(1))
    m = re.match(r"no such column: (?:\w+\.)?(\w+)", msg)
    if m:
        return f'ERROR:  column "{m.group(1)}" does not exist\n' + _pos(sql, m.group(1))
    m = re.match(r"no such function: (\w+)", msg)
    if m:
        return f"ERROR:  function {m.group(1).lower()}() does not exist\n"
    if "not authorized" in msg:
        return "ERROR:  permission denied for schema public\n"
    if "interrupted" in msg:
        return "ERROR:  canceling statement due to statement timeout\n"
    return "ERROR:  syntax error\n"


def _deny(first, low):
    if first == "copy":
        if "program" in low:
            return "ERROR:  must be superuser or a member of the pg_execute_server_program role to COPY to or from an external program\n"
        if re.search(r"\bto\b", low):
            return "ERROR:  must be superuser or a member of the pg_write_server_files role to COPY to a file\n"
        return "ERROR:  must be superuser or a member of the pg_read_server_files role to COPY from a file\n"
    m = re.search(r"(?:into|update|from|table|truncate)\s+(?:only\s+)?(?:public\.)?(\w+)", low)
    if first == "create" or not m or m.group(1) not in TABLES:
        return "ERROR:  permission denied for schema public\n"
    if first in ("drop", "alter", "truncate"):
        return f"ERROR:  must be owner of table {m.group(1)}\n"
    return f"ERROR:  permission denied for table {m.group(1)}\n"


def _auth(action, a1, a2, db, trig):
    ok = (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
          sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE)
    return sqlite3.SQLITE_OK if action in ok else sqlite3.SQLITE_DENY


def _llm_rows(provider, user, keys, minimum):
    try:
        text = "".join(provider.stream(SYS, user, 900))
        a, b = text.find("["), text.rfind("]")
        data = json.loads(text[a:b + 1])
    except Exception:
        return None
    rows = [r for r in data if isinstance(r, dict)
            and all(isinstance(r.get(k), str) and 0 < len(r[k]) <= 60 for k in keys)] \
        if isinstance(data, list) else []
    return rows if len(rows) >= minimum else None


class Psql:
    def __init__(self, provider):
        self.provider, self.conn, self.buf = provider, None, ""

    # ---------- data ----------
    def _build(self):
        rng, today = random.Random(), date.today()
        depts = LORE["departments"]
        people = _llm_rows(
            self.provider,
            f"Invent 18 fictional non-executive employees of {LORE['company']}, a freight logistics "
            f"company. JSON array of objects with keys full_name, department, title. department must "
            f"be one of: {', '.join(depts)}. Use varied international names and realistic job titles.",
            ("full_name", "department", "title"), 8) or [
            {"full_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
             "department": rng.choice(depts), "title": rng.choice(TITLES)} for _ in range(18)]
        emps, used = [], set()

        def add(name, dept, title, salary, hired):
            base, email, k = _slug(name) or "user", None, 1
            email = f"{base}@{LORE['domain']}"
            while email in used:
                k += 1
                email = f"{base}{k}@{LORE['domain']}"
            used.add(email)
            emps.append((len(emps) + 1, name, email, dept, title, hired, float(salary)))

        for role, name in LORE["executives"].items():
            t, d, sal = EXEC_META[role]
            add(name, d, t, sal, date(2008, 1, 1).replace(year=2008 + rng.randrange(9)).isoformat())
        for p in people:
            dept = p["department"] if p["department"] in depts else rng.choice(depts)
            senior = re.search(r"manager|director|head|lead|senior", p["title"], re.I)
            sal = round(rng.randrange(44000, 96000, 500) * (1.3 if senior else 1) / 500) * 500
            hired = (date(2012, 1, 1) + timedelta(days=rng.randrange(365 * 13))).isoformat()
            add(p["full_name"], dept, p["title"], sal, hired)

        pay, months = [], []
        for k in (1, 2, 3):
            y, m = today.year, today.month - k
            if m < 1:
                y, m = y - 1, m + 12
            months.append(date(y, m, 1).isoformat())
        months.reverse()
        for e in emps:
            rate = 0.18 + min(0.14, e[6] / 2000000)
            for per in months:
                gross = round(e[6] / 12 + rng.choice([0, 0, 0, rng.uniform(150, 1800)]), 2)
                tax = round(gross * rate, 2)
                pay.append((len(pay) + 1, e[0], per, gross, tax, round(gross - tax, 2)))

        firms = _llm_rows(
            self.provider,
            "Invent 12 fictional shipper companies that are customers of a freight logistics firm. "
            "JSON array of objects with keys name, country.", ("name", "country"), 6) or [
            {"name": f"{rng.choice(LAST)} {rng.choice(SUFFIX)}", "country": rng.choice(COUNTRIES)}
            for _ in range(12)]
        cust = [(1000 + i + 1, f["name"], f"ops@{_slug(f['name']).replace('.', '')[:22]}.com",
                 f["country"], float(rng.choice(range(25000, 500001, 25000))))
                for i, f in enumerate(firms)]

        ships, ids = [], set()
        status = ["Delivered"] * 6 + ["In Transit"] * 3 + ["Customs Hold", "Delayed"]
        while len(ships) < 40:
            sid = f"HFS-{rng.randrange(100000, 999999)}"
            if sid in ids:
                continue
            ids.add(sid)
            o, d = rng.sample(CITIES, 2)
            ships.append((sid, rng.choice(cust)[0], o, d, rng.choice(status),
                          round(rng.uniform(120, 24000), 2),
                          (today - timedelta(days=rng.randrange(90))).isoformat()))

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("ATTACH ':memory:' AS public")
        conn.execute("ATTACH ':memory:' AS information_schema")
        conn.create_function("now", 0, _now)
        for t, cols in TABLES.items():
            conn.execute(f"CREATE TABLE public.{t} ({', '.join(f'{n} {_sq(ty)}' for n, ty in cols)})")
        for t, rows in (("employees", emps), ("payroll", pay), ("customers", cust), ("shipments", ships)):
            conn.executemany(f"INSERT INTO public.{t} VALUES ({','.join('?' * len(TABLES[t]))})", rows)
        conn.execute("CREATE TABLE information_schema.tables (table_catalog TEXT, table_schema TEXT, table_name TEXT, table_type TEXT)")
        conn.execute("CREATE TABLE information_schema.columns (table_catalog TEXT, table_schema TEXT, table_name TEXT, column_name TEXT, ordinal_position INTEGER, data_type TEXT, is_nullable TEXT)")
        for t, cols in TABLES.items():
            conn.execute("INSERT INTO information_schema.tables VALUES (?,?,?,?)", (DB, "public", t, "BASE TABLE"))
            for i, (n, ty) in enumerate(cols):
                conn.execute("INSERT INTO information_schema.columns VALUES (?,?,?,?,?,?,?)",
                             (DB, "public", t, n, i + 1, ty.split("(")[0], "NO" if n == "id" else "YES"))
        conn.commit()
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100000)
        conn.set_authorizer(_auth)
        self.conn = conn

    # ---------- input handling ----------
    def run(self, line):
        """Returns (output_text, quit)."""
        t = line.strip()
        if not self.buf:
            if t in ("\\q", "exit", "quit"):
                return "", True
            if t.startswith("\\"):
                return self.meta(t), False
            if t == "help":
                return ("You are using psql, the command-line interface to PostgreSQL.\n"
                        "Type:  \\copyright for distribution terms\n"
                        "       \\h for help with SQL commands\n"
                        "       \\? for help with psql commands\n"
                        "       \\g or terminate with semicolon to execute query\n"
                        "       \\q to quit\n"), False
            if not t:
                return "", False
        self.buf = (self.buf + " " + t).strip()
        if not self.buf.endswith(";"):
            return "", False
        sql, self.buf = self.buf, ""
        return self.query(sql), False

    def meta(self, t):
        parts = t.split()
        c, arg = parts[0], (parts[1] if len(parts) > 1 else None)
        if c in ("\\dt", "\\dt+") or (c == "\\d" and not arg):
            rows = [("public", n, "table", USER) for n in sorted(TABLES)]
            return fmt(["Schema", "Name", "Type", "Owner"], rows, "List of relations")
        if c == "\\d":
            cols = TABLES.get(arg.lower().replace("public.", ""))
            if not cols:
                return f'Did not find any relation named "{arg}".\n'
            name = arg.lower().replace("public.", "")
            rows = [(n, ty, "", "not null" if n == "id" else "", "") for n, ty in cols]
            return (fmt(["Column", "Type", "Collation", "Nullable", "Default"], rows,
                        f'Table "public.{name}"').rstrip("\n").rsplit("\n", 1)[0] + "\n"
                    + EXTRA[name] + "\n")
        if c == "\\l":
            rows = [(DB, USER, "UTF8", "en_US.UTF-8", "en_US.UTF-8", ""),
                    ("postgres", "postgres", "UTF8", "en_US.UTF-8", "en_US.UTF-8", ""),
                    ("template0", "postgres", "UTF8", "en_US.UTF-8", "en_US.UTF-8", "=c/postgres"),
                    ("template1", "postgres", "UTF8", "en_US.UTF-8", "en_US.UTF-8", "=c/postgres")]
            return fmt(["Name", "Owner", "Encoding", "Collate", "Ctype", "Access privileges"],
                       sorted(rows), "List of databases")
        if c == "\\du":
            rows = [("postgres", "Superuser, Create role, Create DB, Replication, Bypass RLS", "{}"),
                    ("svc_backup", "", "{}"), ("svc_ops", "Create DB", "{}")]
            return fmt(["Role name", "Attributes", "Member of"], rows, "List of roles")
        if c == "\\conninfo":
            return (f'You are connected to database "{DB}" as user "{USER}" on host "{HOST}" '
                    f'(address "10.20.4.31") at port "5432".\n')
        if c in ("\\c", "\\connect"):
            if arg in (None, DB):
                return f'You are now connected to database "{DB}" as user "{USER}".\n'
            return (f'connection to server at "{HOST}" (10.20.4.31), port 5432 failed: '
                    f'FATAL:  database "{arg}" does not exist\nPrevious connection kept\n')
        if c in ("\\?", "\\h"):
            return "Use \\dt, \\d NAME, \\l, \\du, \\conninfo, \\q\n"
        return f"invalid command {c}\nTry \\? for help.\n"

    # ---------- queries ----------
    def query(self, sql):
        s = sql.strip().rstrip(";").strip()
        low = " ".join(s.lower().split())
        if low in SPECIAL:
            name, fn = SPECIAL[low]
            return fmt([name], [[fn()]])
        first = low.split(" ", 1)[0] if low else ""
        simple = {"begin": "BEGIN", "commit": "COMMIT", "rollback": "ROLLBACK",
                  "set": "SET", "reset": "RESET"}
        if first in simple:
            return simple[first] + "\n"
        if first in WRITE:
            return _deny(first, low)
        if not low:
            return ""
        if first not in ("select", "with"):
            return _pg_error(f'near "{s.split(None, 1)[0]}": syntax error', sql.strip())
        if BLOCK.search(low):
            return _pg_error("not authorized", s)
        s = re.sub(r"\bilike\b", "LIKE", s, flags=re.I)
        s = re.sub(r"::\w+(\(\d+(,\d+)?\))?", "", s)
        if self.conn is None:
            self._build()
        deadline = time.monotonic() + 2.0
        self.conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
        try:
            cur = self.conn.execute(s)
            rows = cur.fetchmany(MAX_ROWS)
            cols = [_colname(d[0]) for d in cur.description] if cur.description else []
        except sqlite3.Error as e:
            return _pg_error(str(e), sql.strip().rstrip(";") + ";")
        finally:
            self.conn.set_progress_handler(None, 0)
        return fmt(cols, rows)