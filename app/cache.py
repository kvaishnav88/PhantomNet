import re, secrets, string
from datetime import datetime, timedelta
from app.files import TEMPLATES

USER = "svc_ops"
HOME = "/home/svc_ops"
FENCE = chr(96) * 3  # markdown code-fence marker
FENCE_LINE = re.compile(r"^" + re.escape(FENCE) + r"[\w-]*\s*$")
UPPER_DIGITS = string.ascii_uppercase + string.digits
ALNUM = string.ascii_letters + string.digits


def _rand(n, alphabet):
    return "".join(secrets.choice(alphabet) for _ in range(n))


def scrub_secrets(line: str) -> str:
    """Replace well-known placeholder secrets that instantly reveal a fake."""
    line = re.sub(r"AKIA[A-Z0-9]*EXAMPLE[A-Z0-9]*",
                  lambda m: "AKIA" + _rand(16, UPPER_DIGITS), line)
    line = re.sub(r"wJalrXUtnFEMI\S*", lambda m: _rand(40, ALNUM + "/+"), line)
    line = re.sub(r"T0{6,}/B0{6,}/X{6,}",
                  lambda m: f"T{_rand(10, UPPER_DIGITS)}/B{_rand(10, UPPER_DIGITS)}/{_rand(24, ALNUM)}",
                  line)
    return line


def stamp(days_ago, hour, minute):
    t = datetime.now() - timedelta(days=days_ago)
    return f"{t:%b} {t.day:>2} {hour:02d}:{minute:02d}"


def _seed():
    d = "drwxr-xr-x"
    root = {n: (d, "root", 4096, stamp(150, 6, 12)) for n in
            ["bin", "boot", "dev", "etc", "home", "lib", "opt", "proc",
             "run", "sbin", "srv", "sys", "usr", "var", "mnt"]}
    root["root"] = ("drwx------", "root", 4096, stamp(20, 8, 2))
    root["tmp"] = ("drwxrwxrwt", "root", 4096, stamp(0, 3, 0))
    return {
        "/": root,
        "/home": {
            "svc_ops": ("drwxr-x---", USER, 4096, stamp(1, 18, 12)),
            "dreyes": ("drwxr-x---", "dreyes", 4096, stamp(3, 9, 40)),
            "emarchetti": ("drwxr-x---", "emarchetti", 4096, stamp(5, 15, 22)),
        },
        HOME: {
            ".ssh": ("drwx------", USER, 4096, stamp(41, 10, 41)),
            ".bash_history": ("-rw-------", USER, 2217, stamp(1, 18, 12)),
            ".bashrc": ("-rw-r--r--", USER, 3771, stamp(120, 11, 3)),
            ".profile": ("-rw-r--r--", USER, 807, stamp(120, 11, 3)),
            "backup_hfs.sh": ("-rwxr-xr-x", USER, 642, stamp(23, 16, 20)),
            "deploy_notes.txt": ("-rw-r--r--", USER, 1530, stamp(9, 14, 55)),
            "logs": (d, USER, 4096, stamp(2, 7, 30)),
            "scripts": (d, USER, 4096, stamp(17, 13, 5)),
            "secret_keys.txt": ("-rw-------", USER, 1184, stamp(6, 10, 47)),
        },
        HOME + "/logs": {
            "sync.log": ("-rw-r--r--", USER, 48211, stamp(0, 6, 0)),
            "telematics_ingest.log": ("-rw-r--r--", USER, 903442, stamp(0, 7, 15)),
        },
        HOME + "/scripts": {
            "rotate_logs.sh": ("-rwxr-xr-x", USER, 388, stamp(60, 9, 9)),
            "customs_export.py": ("-rw-r--r--", USER, 2764, stamp(17, 13, 5)),
        },
        HOME + "/.ssh": {
            "authorized_keys": ("-rw-------", USER, 574, stamp(41, 10, 41)),
            "known_hosts": ("-rw-r--r--", USER, 1332, stamp(12, 8, 30)),
        },
    }


class Session:
    def __init__(self):
        self.cwd = HOME
        self.fs = _seed()      # dir path -> {name: (perm, owner, size, mtime)}
        self.files = {}        # abs path -> file content (the consistency cache)
        self.outputs = {}      # (cwd, command) -> generated output
        for path, make in TEMPLATES.items():
            content = make()
            self.files[path] = content
            parent, name = path.rsplit("/", 1)
            parent = parent or "/"
            entry = self.fs.get(parent, {}).get(name)
            if entry:  # make the ls size match the real content
                self.fs[parent][name] = (entry[0], entry[1], len(content.encode()), entry[3])