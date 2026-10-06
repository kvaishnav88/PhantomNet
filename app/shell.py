import posixpath, re, shlex
from app.sqlmock import Psql, DB as PG_DB, HOST as PG_HOST, USER as PG_USER
from datetime import datetime
from app.cache import USER, HOME, stamp, scrub_secrets, FENCE_LINE
from app.lore import LORE, build_system_prompt, build_command_prompt
from app.procs import ps_output, uptime_output

ROOT_ENTRY = ("drwxr-xr-x", "root", 4096, stamp(150, 6, 12))
DENIED = {"/etc/shadow", "/etc/sudoers", "/root/.bash_history"}
UNAME_A = "Linux hfs-app-02 5.15.0-117-generic #127-Ubuntu SMP Fri Jul 5 20:13:28 UTC 2024 x86_64 x86_64 x86_64 GNU/Linux\n"
LLM_COMMANDS = {
    "ps", "netstat", "ss", "ifconfig", "ip", "env", "printenv", "history",
    "df", "du", "free", "uptime", "w", "who", "last", "lsof", "top",
    "head", "tail", "less", "more", "grep", "find", "file", "stat", "wc",
    "date", "echo", "crontab", "systemctl", "docker", "psql", "mysql",
    "curl", "wget", "ping", "ssh", "sudo", "nmap", "python", "python3",
    "sort", "uniq", "awk", "sed", "cut", "strings", "base64", "tar", "unzip",
}

def make_system() -> str:
    now = datetime.now()
    return build_system_prompt() + (
        f"\nCURRENT DATE/TIME: {now:%a %b %d %H:%M:%S} UTC {now.year}. "
        "Use this year for recent dates and never invent dates after it."
    )


def _abs(session, path):
    if path == "~" or path.startswith("~/"):
        path = HOME + path[1:]
    if not path.startswith("/"):
        path = posixpath.join(session.cwd, path)
    return posixpath.normpath(path)


def _lookup(session, path):
    if path == "/":
        return ROOT_ENTRY
    parent, name = posixpath.split(path)
    return session.fs.get(parent, {}).get(name)


def _can_enter(entry):
    return entry[1] == USER or entry[0][9] in "xt"


def _clean_stream(chunks):
    """Line-buffered: drop markdown fences, scrub placeholder secrets, keep streaming."""
    buf = ""
    for c in chunks:
        buf += c
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            if FENCE_LINE.match(line):
                continue
            yield scrub_secrets(line) + "\n"
    if buf.strip() and not FENCE_LINE.match(buf):
        yield scrub_secrets(buf) + "\n"


def _render_ls(entries, flags, dir_time):
    items = dict(entries)
    hidden = "a" in flags or "A" in flags
    if "a" in flags:
        items["."] = ("drwxr-xr-x", USER, 4096, dir_time)
        items[".."] = ("drwxr-xr-x", "root", 4096, dir_time)
    names = sorted((n for n in items if hidden or not n.startswith(".")),
                   key=lambda n: (n not in (".", ".."), n.lstrip(".").lower()))
    if not names:
        return ""
    if "l" not in flags:
        return "  ".join(names) + "\n"
    ow = max(len(items[n][1]) for n in names)
    sw = max(len(str(items[n][2])) for n in names)
    total = sum(((items[n][2] + 4095) // 4096) * 4 for n in names)
    lines = [f"total {total}"]
    for n in names:
        perm, owner, size, mtime = items[n]
        links = 2 if perm[0] == "d" else 1
        lines.append(f"{perm} {links:>2} {owner:<{ow}} {owner:<{ow}} {size:>{sw}} {mtime} {n}")
    return "\n".join(lines) + "\n"


def _llm_cached(session, command, provider, system):
    key = (session.cwd, " ".join(command.split()))
    if key in session.outputs:
        yield session.outputs[key]
        return
    prompt = build_command_prompt(session.cwd, command)
    listing = ", ".join(sorted(session.fs.get(session.cwd, {})))
    if listing:
        prompt += f"\nFILES IN CWD: {listing}"
    out = []
    for line in _clean_stream(provider.stream(system, prompt)):
        out.append(line)
        yield line
    session.outputs[key] = "".join(out)


def _cd(session, paths):
    if not paths or paths[0] == "~":
        session.cwd = HOME
        return ""
    target = _abs(session, paths[0])
    entry = _lookup(session, target)
    if entry is None:
        return f"bash: cd: {paths[0]}: No such file or directory\n"
    if entry[0][0] != "d":
        return f"bash: cd: {paths[0]}: Not a directory\n"
    if not _can_enter(entry):
        return f"bash: cd: {paths[0]}: Permission denied\n"
    session.cwd = target
    return ""


def _ls(session, paths, flags, provider, system, command):
    p = paths[0] if paths else "."
    path = _abs(session, p)
    entry = _lookup(session, path)
    if entry is None:
        yield f"ls: cannot access '{p}': No such file or directory\n"
    elif entry[0][0] != "d":
        yield p + "\n"
    elif not _can_enter(entry):
        yield f"ls: cannot open directory '{p}': Permission denied\n"
    elif path in session.fs:
        yield _render_ls(session.fs[path], flags, entry[3])
    else:
        yield from _llm_cached(session, command, provider, system)


def _cat(session, p, provider, system):
    path = _abs(session, p)
    entry = _lookup(session, path)
    if path in DENIED:
        yield f"cat: {p}: Permission denied\n"
        return
    if entry is not None and entry[0][0] == "d":
        yield f"cat: {p}: Is a directory\n"
        return
    if entry is None:
        parent = posixpath.dirname(path)
        pe = _lookup(session, parent)
        # parent must be a real directory we do NOT fully control (otherwise the file doesn't exist)
        if pe is None or pe[0][0] != "d" or parent in session.fs:
            yield f"cat: {p}: No such file or directory\n"
            return
    if path in session.files:
        yield session.files[path]
        return
    hint = ""
    if entry is not None and entry[2] < 3000:
        hint += f"\nFILE SIZE: about {entry[2]} bytes."
    if path == "/etc/passwd":
        hint += "\nINCLUDE LOGIN USERS: svc_ops (uid 1001), dreyes, emarchetti, plus normal system accounts."
    prompt = build_command_prompt(session.cwd, f"cat {path}") + hint
    out = []
    for line in _clean_stream(provider.stream(system, prompt, max_tokens=700)):
        out.append(line)
        yield line
    session.files[path] = "".join(out)


def _psql_cmd(session, args, provider):
    flags = {"-h": "host", "--host": "host", "-U": "user", "--username": "user",
             "-d": "db", "--dbname": "db", "-c": "cmd", "--command": "cmd", "-p": "port"}
    opts, i = {}, 0
    while i < len(args):
        a = args[i]
        if a in flags and i + 1 < len(args):
            opts[flags[a]] = args[i + 1]
            i += 2
        elif a == "-l":
            opts["list"] = True
            i += 1
        else:
            if not a.startswith("-") and "db" not in opts:
                opts["db"] = a
            i += 1
    host = opts.get("host")
    user = opts.get("user", PG_USER)
    db = opts.get("db", user)
    if not host:
        yield ('psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" '
               "failed: No such file or directory\n\tIs the server running locally and accepting "
               "connections on that socket?\n")
        return
    if host in ("localhost", "127.0.0.1"):
        yield (f'psql: error: connection to server at "{host}" (127.0.0.1), port 5432 failed: '
               "Connection refused\n\tIs the server running on that host and accepting TCP/IP "
               "connections?\n")
        return
    if host not in (PG_HOST, PG_HOST + ".halcyon-freight.internal"):
        yield f'psql: error: could not translate host name "{host}" to address: Name or service not known\n'
        return
    target = f'connection to server at "{host}" (10.20.4.31), port 5432'
    if user != PG_USER:
        yield f'psql: error: {target} failed: FATAL:  password authentication failed for user "{user}"\n'
        return
    if db != PG_DB:
        yield f'psql: error: {target} failed: FATAL:  database "{db}" does not exist\n'
        return
    ps = Psql(provider)
    if opts.get("list"):
        yield ps.meta("\\l")
        return
    if "cmd" in opts:
        q = opts["cmd"].strip()
        text, _ = ps.run(q if q.endswith(";") or q.startswith("\\") else q + ";")
        yield text
        return
    session.psql = ps
    yield ("psql (14.12 (Ubuntu 14.12-0ubuntu0.22.04.1))\n"
           "SSL connection (protocol: TLSv1.3, cipher: TLS_AES_256_GCM_SHA384, bits: 256, compression: off)\n"
           'Type "help" for help.\n\n')
    
def run_command(session, command, provider, system):
    command = command.strip()[:200]
    if not command:
        return
    if session.psql:
        text, quit_ = session.psql.run(command)
        if quit_:
            session.psql = None
        if text:
            yield text
        return
    try:
        argv = shlex.split(command)
    except ValueError:
        yield "bash: unexpected EOF while looking for matching quote\n"
        return
    while len(argv) > 1 and re.match(r"^[A-Za-z_]+=", argv[0]):
        argv = argv[1:]
    cmd, args = argv[0], argv[1:]
    flags = "".join(a[1:] for a in args if a.startswith("-") and len(a) > 1)
    paths = [a for a in args if not a.startswith("-")]

    if cmd == "pwd":
        yield session.cwd + "\n"
    elif cmd == "whoami":
        yield USER + "\n"
    elif cmd == "id":
        yield f"uid=1001({USER}) gid=1001({USER}) groups=1001({USER}),27(sudo)\n"
    elif cmd == "hostname":
        yield LORE["hostname"] + "\n"
    elif cmd == "uname":
        yield UNAME_A if "a" in flags else "Linux\n"
    elif cmd == "cd":
        msg = _cd(session, paths)
        if msg:
            yield msg
    elif cmd == "ls":
        yield from _ls(session, paths, flags, provider, system, command)
    elif cmd == "cat" and paths:
        for p in paths:
            yield from _cat(session, p, provider, system)
    elif cmd == "psql":
        yield from _psql_cmd(session, args, provider)
    elif cmd == "uptime" and not args:
        yield uptime_output(session)
    elif cmd == "ps":
        text = ps_output(session, command)
        if text is None:
            yield from _llm_cached(session, command, provider, system)
        else:
            yield text
    elif cmd in LLM_COMMANDS:
        yield from _llm_cached(session, command, provider, system)
    else:
        yield f"bash: {cmd}: command not found\n"