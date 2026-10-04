import base64, secrets, string
from datetime import datetime, timedelta

UPPER_DIGITS = string.ascii_uppercase + string.digits
ALNUM = string.ascii_letters + string.digits
HEX = "0123456789abcdef"


def _rand(n, alphabet):
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _pem(header, prefix, nbytes):
    body = base64.b64encode(secrets.token_bytes(nbytes)).decode()
    body = prefix + body[len(prefix):]
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "\n".join([f"-----BEGIN {header}-----", *lines, f"-----END {header}-----"])


def passwd():
    rows = [
        "root:x:0:0:root:/root:/bin/bash",
        "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin",
        "bin:x:2:2:bin:/bin:/usr/sbin/nologin",
        "sys:x:3:3:sys:/dev:/usr/sbin/nologin",
        "sync:x:4:65534:sync:/bin:/bin/sync",
        "games:x:5:60:games:/usr/games:/usr/sbin/nologin",
        "man:x:6:12:man:/var/cache/man:/usr/sbin/nologin",
        "lp:x:7:7:lp:/var/spool/lpd:/usr/sbin/nologin",
        "mail:x:8:8:mail:/var/mail:/usr/sbin/nologin",
        "news:x:9:9:news:/var/spool/news:/usr/sbin/nologin",
        "uucp:x:10:10:uucp:/var/spool/uucp:/usr/sbin/nologin",
        "proxy:x:13:13:proxy:/bin:/usr/sbin/nologin",
        "www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin",
        "backup:x:34:34:backup:/var/backups:/usr/sbin/nologin",
        "list:x:38:38:Mailing List Manager:/var/list:/usr/sbin/nologin",
        "irc:x:39:39:ircd:/run/ircd:/usr/sbin/nologin",
        "_apt:x:42:65534::/nonexistent:/usr/sbin/nologin",
        "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin",
        "systemd-network:x:100:102:systemd Network Management,,,:/run/systemd:/usr/sbin/nologin",
        "systemd-resolve:x:101:103:systemd Resolver,,,:/run/systemd:/usr/sbin/nologin",
        "messagebus:x:102:105::/nonexistent:/usr/sbin/nologin",
        "sshd:x:103:65534::/run/sshd:/usr/sbin/nologin",
        "svc_ops:x:1001:1001:Ops Service Account,,,:/home/svc_ops:/bin/bash",
        "dreyes:x:1002:1002:Daniel Reyes,,,:/home/dreyes:/bin/bash",
        "emarchetti:x:1003:1003:Elena Marchetti,,,:/home/emarchetti:/bin/bash",
    ]
    return "\n".join(rows) + "\n"


def secret_keys():
    day = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    pem = _pem("RSA PRIVATE KEY", "MIIEowIBAAKCAQEA", 1190)
    return f"""# hfs service credentials - ops only, do not forward
# last rotated {day} (svc_ops)
# TODO: move all of this into vault before the Meridian cutover

# --- postgres (hfs-db-01) ---
DB_HOST=hfs-db-01.halcyon-freight.internal
DB_USER=svc_ops
DB_PASS=Tr4nsit!Ops{_rand(2, string.digits)}

# --- internal apis ---
ALBATROSS_API_KEY=alb_live_{_rand(32, HEX)}
MERIDIAN_SSO_TOKEN=mrd_{_rand(40, ALNUM)}
COBALT_TELEMATICS_TOKEN=cbt-{_rand(8, HEX)}-{_rand(4, HEX)}-{_rand(12, HEX)}

# --- aws (customs-docs bucket) ---
AWS_ACCESS_KEY_ID=AKIA{_rand(16, UPPER_DIGITS)}
AWS_SECRET_ACCESS_KEY={_rand(40, ALNUM + "/+")}
AWS_DEFAULT_REGION=eu-west-1

# --- misc ---
SFTP_USER=svc_ops_sftp
SFTP_PASS=Hfs-sftp-{_rand(6, ALNUM)}
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T{_rand(9, UPPER_DIGITS)}/B{_rand(10, UPPER_DIGITS)}/{_rand(24, ALNUM)}

# deploy key for hfs-files-01
{pem}
"""


TEMPLATES = {
    "/etc/passwd": passwd,
    "/home/svc_ops/secret_keys.txt": secret_keys,
}