import posixpath, shlex
from datetime import datetime
from app.cache import USER, HOME, stamp, scrub_secrets, FENCE_LINE
from app.lore import LORE, build_system_prompt, build_command_prompt

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


def run_command(session, command, provider, system):
    command = command.strip()[:200]
    if not command:
        return
    try:
        argv = shlex.split(command)
    except ValueError:
        yield "bash: unexpected EOF while looking for matching quote\n"
        return
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
    elif cmd in LLM_COMMANDS:
        yield from _llm_cached(session, command, provider, system)
    else:
        yield f"bash: {cmd}: command not found\n"