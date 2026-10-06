import random, re, shlex
from datetime import datetime, timedelta

# user, pid, ppid, %cpu, %mem, vsz, rss, tty, stat, cpu_seconds, command
SYS = [
    ("root", 1, 0, 0.0, 0.3, 168936, 13148, "?", "Ss", 9, "/sbin/init"),
    ("root", 2, 0, 0.0, 0.0, 0, 0, "?", "S", 0, "[kthreadd]"),
    ("root", 3, 2, 0.0, 0.0, 0, 0, "?", "I<", 0, "[rcu_gp]"),
    ("root", 4, 2, 0.0, 0.0, 0, 0, "?", "I<", 0, "[rcu_par_gp]"),
    ("root", 15, 2, 0.0, 0.0, 0, 0, "?", "S", 1, "[ksoftirqd/0]"),
    ("root", 16, 2, 0.0, 0.0, 0, 0, "?", "I", 12, "[rcu_sched]"),
    ("root", 17, 2, 0.0, 0.0, 0, 0, "?", "S", 0, "[migration/0]"),
    ("root", 293, 1, 0.0, 0.7, 64288, 28392, "?", "S<s", 21, "/lib/systemd/systemd-journald"),
    ("root", 330, 1, 0.0, 0.2, 26524, 6180, "?", "Ss", 2, "/lib/systemd/systemd-udevd"),
    ("systemd-network", 672, 1, 0.0, 0.2, 19108, 7964, "?", "Ss", 1, "/lib/systemd/systemd-networkd"),
    ("systemd-resolve", 674, 1, 0.0, 0.3, 25020, 13104, "?", "Ss", 5, "/lib/systemd/systemd-resolved"),
    ("root", 701, 1, 0.0, 0.1, 6616, 2704, "?", "Ss", 0, "/usr/sbin/cron -f -P"),
    ("messagebus", 703, 1, 0.0, 0.1, 8700, 5008, "?", "Ss", 1,
     "@dbus-daemon --system --address=systemd: --nofork --nopidfile --systemd-activation --syslog-only"),
    ("root", 718, 1, 0.0, 0.2, 15348, 7488, "?", "Ss", 2, "/lib/systemd/systemd-logind"),
    ("root", 735, 1, 0.0, 0.2, 15436, 9588, "?", "Ss", 0,
     "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups"),
    ("root", 760, 1, 0.0, 0.4, 32684, 18000, "?", "Ss", 0,
     "/usr/bin/python3 /usr/bin/networkd-dispatcher --run-startup-triggers"),
    ("root", 802, 1, 0.0, 0.1, 55260, 5240, "?", "Ss", 0,
     "nginx: master process /usr/sbin/nginx -g daemon on; master_process on;"),
    ("www-data", 803, 802, 0.0, 0.2, 56016, 8244, "?", "S", 3, "nginx: worker process"),
    ("www-data", 804, 802, 0.0, 0.2, 56016, 7988, "?", "S", 3, "nginx: worker process"),
    ("svc_ops", 911, 1, 1.4, 1.9, 412736, 77120, "?", "Ssl", 2340,
     "/usr/bin/python3 /opt/hfs/cobalt/ingest.py --config /etc/hfs/cobalt.yml"),
    ("root", 912, 1, 0.0, 0.0, 5836, 1072, "tty1", "Ss+", 0,
     "/sbin/agetty -o -p -- \\u --noclear tty1 linux"),
]


def _state(session):
    st = getattr(session, "proc", None)
    if st is None:
        rng, now = random.Random(), datetime.now()
        boot = (now - timedelta(days=rng.randrange(9, 40))).replace(
            hour=rng.randrange(24), minute=rng.randrange(60), second=rng.randrange(60))
        base = rng.randrange(18000, 24000)
        st = {"boot": boot, "start": now, "base": base, "next": base + 90}
        session.proc = st
    return st


def _user(u):
    return u if len(u) <= 8 else u[:7] + "+"


def _when(t, now):
    return t.strftime("%H:%M") if t.date() == now.date() else t.strftime("%b%d")


def _rows(st, ps_cmd, grep_cmd=None):
    b, boot, start = st["base"], st["boot"], st["start"]
    rows = [r + (boot,) for r in SYS]
    rows += [
        ("root", b, 735, 0.0, 0.3, 17176, 10952, "?", "Ss", 0, "sshd: svc_ops [priv]", start),
        ("svc_ops", b + 22, 1, 0.0, 0.2, 16932, 9500, "?", "Ss", 0, "/lib/systemd/systemd --user", start),
        ("svc_ops", b + 23, b + 22, 0.0, 0.0, 170540, 3512, "?", "S", 0, "(sd-pam)", start),
        ("svc_ops", b + 60, b, 0.0, 0.1, 17304, 6416, "?", "S", 0, "sshd: svc_ops@pts/0", start),
        ("svc_ops", b + 61, b + 60, 0.0, 0.1, 8728, 5372, "pts/0", "Ss", 0, "-bash", start),
    ]
    pid = st["next"]
    st["next"] += random.randrange(3, 9)
    rows.append(("svc_ops", pid, b + 61, 0.0, 0.0, 10620, 3300, "pts/0", "R+", 0, ps_cmd, start))
    if grep_cmd:
        rows.append(("svc_ops", pid + 1, b + 61, 0.0, 0.0, 9032, 2480, "pts/0", "S+", 0, grep_cmd, start))
    return sorted(rows, key=lambda r: r[1])


def _aux(rows, now):
    out = [f"{'USER':<8} {'PID':>7} {'%CPU':>4} {'%MEM':>4} {'VSZ':>6} {'RSS':>5} "
           f"{'TTY':<8} {'STAT':<4} {'START':>5} {'TIME':>6} COMMAND"]
    for u, pid, ppid, cpu, mem, vsz, rss, tty, stat, secs, cmd, t in rows:
        tm = f"{secs // 60}:{secs % 60:02d}"
        out.append(f"{_user(u):<8} {pid:>7} {cpu:>4.1f} {mem:>4.1f} {vsz:>6} {rss:>5} "
                   f"{tty:<8} {stat:<4} {_when(t, now):>5} {tm:>6} {cmd}")
    return out


def _ef(rows, now):
    out = [f"{'UID':<8} {'PID':>7} {'PPID':>7} {'C':>2} {'STIME':>5} {'TTY':<8} {'TIME':>8} CMD"]
    for u, pid, ppid, cpu, mem, vsz, rss, tty, stat, secs, cmd, t in rows:
        tm = f"{secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}"
        out.append(f"{_user(u):<8} {pid:>7} {ppid:>7} {int(cpu):>2} {_when(t, now):>5} "
                   f"{tty:<8} {tm:>8} {cmd}")
    return out


def _plain(rows):
    out = [f"{'PID':>7} {'TTY':<8} {'TIME':>8} CMD"]
    for r in rows:
        if r[1] >= r[1] and r[7] == "pts/0":
            name = r[10].lstrip("-").split()[0]
            out.append(f"{r[1]:>7} {r[7]:<8} {'00:00:00':>8} {name}")
    return out


def ps_output(session, command):
    """Returns the text for a ps command, or None if we don't handle that form."""
    left, _, right = command.partition("|")
    try:
        argv = shlex.split(left)
    except ValueError:
        return None
    grep = None
    grep_cmd = None
    if right.strip():
        try:
            g = shlex.split(right)
        except ValueError:
            return None
        if not g or g[0] != "grep":
            return None
        invert = ignore = False
        pat = None
        for a in g[1:]:
            if a.startswith("-") and len(a) > 1 and pat is None:
                if set(a[1:]) - set("viE"):
                    return None
                invert |= "v" in a
                ignore |= "i" in a
            elif pat is None:
                pat = a
            else:
                return None
        if pat is None:
            return None
        try:
            rx = re.compile(pat, re.I if ignore else 0)
        except re.error:
            return None
        grep = (rx, invert)
        grep_cmd = "grep --color=auto " + " ".join(g[1:])

    args = argv[1:]
    letters = "".join(a.lstrip("-") for a in args)
    if args and not letters.isalpha():
        return None
    ps_cmd = " ".join(argv)
    now = datetime.now()
    st = _state(session)
    if not args:
        lines = _plain(_rows(st, ps_cmd, grep_cmd))
    elif args[0].startswith("-") and ("e" in letters or "A" in letters) and "f" in letters:
        lines = _ef(_rows(st, ps_cmd, grep_cmd), now)
    elif not args[0].startswith("-") or not ({"e", "A"} & set(letters)):
        if not ({"a", "x", "u"} & set(letters)):
            return None
        lines = _aux(_rows(st, ps_cmd, grep_cmd), now)
    else:
        return None
    if grep:
        rx, invert = grep
        lines = [l for l in lines if bool(rx.search(l)) != invert]
    return "".join(l + "\n" for l in lines)


def uptime_output(session):
    st, now = _state(session), datetime.now()
    d = now - st["boot"]
    h, m = d.seconds // 3600, d.seconds // 60 % 60
    l1, l2, l3 = (random.uniform(0, 0.25) for _ in range(3))
    return (f" {now:%H:%M:%S} up {d.days} day{'s' if d.days != 1 else ''}, {h:>2}:{m:02d},  "
            f"1 user,  load average: {l1:.2f}, {l2:.2f}, {l3:.2f}\n")