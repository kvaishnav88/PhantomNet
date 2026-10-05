# PhantomNet: Generative Cyber-Deception (LLM Honeypot)

A honeypot that doesn't look like one. Traditional honeypots are static: fake servers with repetitive, obviously planted data that experienced attackers spot quickly. PhantomNet puts a shell in front of the attacker and generates the fake corporate universe around them on demand, keeping it consistent for the whole session.

**Live demo:** _coming soon (deployment in progress)_
**Status:** backend complete and tested locally; analyst dashboard and deployment in progress (see [Roadmap](#roadmap)).

---

## How it works

An "attacker" connects to a WebSocket shell that looks like an Ubuntu server at a fictional freight company, **Halcyon Freight Systems**. Every command is handled by one of three layers:

```
Attacker (WebSocket)
        |
        v
[Session Simulator]   FastAPI. Parses each command.
        |
        +--> [Virtual filesystem + templates]   Python. ls, cd, cat, pwd, whoami, id...
        |       Fixed names, permissions, dates and sizes.
        |       /etc/passwd and secret_keys.txt are built in code.
        |       No LLM call, ~0 ms.
        |
        +--> [Lore Engine]   LLM (Groq by default, Ollama optional).
        |       Generates output for open-ended commands (ps, df, netstat, ...)
        |       and files that aren't templated, prompted with the company "lore"
        |       so names, executives and projects stay consistent.
        |
        +--> [Consistency Cache]   In-memory, per session.
                Same file or command gives byte-identical output on repeat.
        |
        v
[Abuse protection]   Per-IP limits, session caps, global daily LLM budget.
```

### Design decisions

- **The LLM never invents the filesystem structure.** Early tests showed the model contradicting itself: `ls` omitted a file that `cat` then returned, directories appeared twice, listings were cut off. Python now owns structure, permissions, sizes and dates. The LLM only writes content for files and commands that can't be templated.
- **The most inspected files are templated, not generated.** `/etc/passwd` and `secret_keys.txt` are built in Python so they are never truncated and never contain tells such as the AWS documentation example keys (`AKIAIOSFODNN7EXAMPLE`).
- **Per-session canary credentials.** Every session gets freshly randomized fake keys, so if an attacker reuses a credential elsewhere, you can tie it back to the session that received it.
- **Unknown commands never reach the LLM.** A command allowlist decides what goes to the model. Everything else returns `bash: <cmd>: command not found`, exactly one line, like real bash.
- **Output is cleaned in a streaming pass.** Markdown code fences are stripped and placeholder secrets are replaced before anything reaches the attacker.

## Features

- Interactive fake shell over WebSocket with realistic Ubuntu banner, prompt and `Last login` line
- Virtual filesystem with correct `ls -la` formatting, permissions and `Permission denied` behavior
- Consistent file contents across repeated reads within a session
- LLM provider interface: **Groq** (default) or **Ollama** (local) via one environment variable
- Streaming responses with time-to-first-token measurement (see [Performance](#performance))
- Prompt-injection resistance (see [Security](#security))
- Public-ready abuse protection (see [Abuse protection](#abuse-protection))

## Simulated vs. real

Stated plainly, because this is a scoped prototype of a larger idea:

| Concept | What this project does | What a production system would do |
|---|---|---|
| Network interception | Attacker connects directly to the honeypot endpoint | Redirect unauthorized SSH/DB traffic using iptables or eBPF |
| Generative filesystem | Simulated interactive shell with a virtual filesystem | A real FUSE mount where files are generated on read |
| Mock PostgreSQL | Planned: simplified query endpoint | Implementation of the PostgreSQL wire protocol |
| Context retention | Per-session in-memory cache | Vector store (e.g. ChromaDB) for fuzzy recall |
| Local LLM | Groq (cloud) for the public demo, Ollama supported locally | Local model so no data leaves the network |

On the last row: the honeypot only ever sends **fake lore** to the LLM, never real company data, so the privacy reason for preferring a local model doesn't apply to this deployment. Set `LLM_PROVIDER=ollama` to run fully local.

## Security

- **No command is ever executed.** The simulator interprets commands; it does not call `subprocess` or touch the real filesystem. A container escape isn't possible because there is no container to escape from.
- **Attacker input is untrusted.** Input is truncated to 200 characters, and the system prompt tells the model to treat it as shell input, never as instructions. Attempts like "ignore previous instructions" get a normal `command not found`.
- **Secrets stay server-side.** The Groq key lives in `.env` (git-ignored) and is never sent to the client.
- **Everything fake looks fake only to us.** Credentials are randomly generated and valid in format only. The RSA key is random bytes in PEM framing and would be rejected by `openssl`.

## Abuse protection

Because the endpoint is public and every LLM call uses real quota:

| Control | Limit |
|---|---|
| Concurrent sessions per IP | 2 |
| Connection attempts per IP | 6 per minute |
| Commands per IP | 20 per minute |
| Session length | 10 minutes |
| Idle timeout | 2 minutes |
| Incoming message size | 4 KB |
| LLM output | Capped with `max_tokens` on every call |
| Global LLM budget | Configurable per day (default 500). When spent, LLM-backed commands return a believable error while the templated shell keeps working |

## Performance

The spec target is under 500 ms to first token. In local testing against Groq:

- Templated commands (`ls`, `cat`, `cd`, `whoami`): effectively instant, no LLM call
- LLM-backed commands: time-to-first-token typically 150-550 ms (first call after startup is slower)

Numbers vary with network and model load.

## Run locally

Requires Python 3.12 and a [Groq API key](https://console.groq.com).

```powershell
git clone https://github.com/kvaishnav88/PhantomNet.git
cd PhantomNet
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env`:

```
GROQ_API_KEY=your_key_here
```

Start the server:

```powershell
uvicorn app.main:app --port 8000 --ws-max-size 4096
```

In a second terminal (venv active), connect with the test client:

```powershell
python test_client.py
```

Try `ls -la`, `cat secret_keys.txt`, `cd logs`, `ps aux`, `exit`. Health check: `http://localhost:8000/health`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | required | Groq credentials |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Model used for generation |
| `LLM_PROVIDER` | `groq` | Set to `ollama` for a local model |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model |
| `DAILY_LLM_BUDGET` | `500` | Max LLM calls per day |

## Project structure

```
PhantomNet/
├── app/
│   ├── main.py     # FastAPI app, /ws shell endpoint, /health
│   ├── shell.py    # command handling: templates, virtual FS, LLM fallback
│   ├── cache.py    # session state, virtual filesystem, output cleaning
│   ├── files.py    # templated /etc/passwd and secret_keys.txt
│   ├── lore.py     # company lore and system prompts
│   ├── llm.py      # LLMProvider interface (Groq / Ollama)
│   └── limits.py   # rate limiting and daily LLM budget
├── test_client.py  # terminal WebSocket client
├── test_shell.py   # shell behavior checks
└── requirements.txt
```

## Roadmap

- [x] Lore engine and consistent company universe
- [x] Virtual filesystem with consistency cache
- [x] WebSocket shell with abuse protection
- [x] LLM provider interface (Groq / Ollama)
- [ ] Templated `ps` output
- [ ] Live analyst dashboard (Next.js): stream sessions in real time
- [ ] Behavioral analysis: LLM scoring of attacker skill and goals (e.g. credential theft vs. ransomware)
- [ ] Simplified mock SQL endpoint
- [ ] Deployment: backend on Render, frontend on Vercel

## Known limitations

- Only `/` and the home directory tree are fully seeded; other directories are browsable one level deep, with LLM-generated contents.
- Only an allowlist of commands is supported; anything else returns `command not found`.
- State is in memory and per session, so restarting the server resets everything.
- On Render's free tier the first request after idle can take about a minute (cold start).

## Disclaimer

PhantomNet is a deception and research prototype. All companies, people, hosts and credentials shown are fictional.
