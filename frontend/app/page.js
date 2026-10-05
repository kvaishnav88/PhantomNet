"use client";
import { useEffect, useReducer, useRef, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const MAX_FEED = 200;
const initial = { sessions: {}, order: [], feed: [], stats: null };
const SUGGESTIONS = ["ls -la", "cat secret_keys.txt", "cat /etc/passwd", "ps aux", "whoami"];

function touch(state, sid, patch) {
  const prev = state.sessions[sid];
  const next = { sid, ip: "?", ts: 0, active: true, count: 0, analysis: null, ...prev, ...patch };
  const order = prev ? state.order : [sid, ...state.order];
  return { ...state, sessions: { ...state.sessions, [sid]: next }, order };
}

function reduce(state, ev) {
  switch (ev.type) {
    case "reset": return initial;
    case "stats": return { ...state, stats: ev };
    case "session_start": return touch(state, ev.sid, { ip: ev.ip, ts: ev.ts, active: true });
    case "session_end": return touch(state, ev.sid, { active: false });
    case "analysis": return touch(state, ev.sid, { analysis: ev });
    case "command": {
      const s = touch(state, ev.sid, { count: (state.sessions[ev.sid]?.count || 0) + 1 });
      return { ...s, feed: [...s.feed, ev].slice(-MAX_FEED) };
    }
    default: return state;
  }
}

function useMonitor(dispatch, setConn) {
  useEffect(() => {
    let ws, timer, tries = 0, stop = false;
    const open = () => {
      setConn("connecting");
      ws = new WebSocket(`${BASE}/monitor`);
      ws.onopen = () => { tries = 0; dispatch({ type: "reset" }); setConn("live"); };
      ws.onmessage = (m) => { try { dispatch(JSON.parse(m.data)); } catch {} };
      ws.onclose = () => {
        if (stop) return;
        setConn("reconnecting");
        timer = setTimeout(open, Math.min(1000 * 2 ** tries++, 15000));
      };
      ws.onerror = () => ws.close();
    };
    open();
    return () => { stop = true; clearTimeout(timer); if (ws) ws.close(); };
  }, [dispatch, setConn]);
}

function Terminal() {
  const [out, setOut] = useState("");
  const [status, setStatus] = useState("idle");
  const [slow, setSlow] = useState(false);
  const [line, setLine] = useState("");
  const ws = useRef(null);
  const box = useRef(null);
  const hist = useRef([]);
  const pos = useRef(0);

  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [out]);
  useEffect(() => () => { if (ws.current) ws.current.close(); }, []);

  function connect() {
    setOut("");
    setStatus("connecting");
    setSlow(false);
    const slowTimer = setTimeout(() => setSlow(true), 4000);
    const sock = new WebSocket(`${BASE}/ws`);
    ws.current = sock;
    sock.onopen = () => { clearTimeout(slowTimer); setSlow(false); setStatus("open"); };
    sock.onmessage = (m) => setOut((o) => (o + m.data).slice(-30000));
    sock.onclose = () => { clearTimeout(slowTimer); setSlow(false); setStatus("closed"); };
    sock.onerror = () => sock.close();
  }

  function submit(cmd) {
    if (status !== "open" || !ws.current) return;
    setOut((o) => o + cmd + "\n");
    if (cmd.trim()) hist.current.push(cmd);
    pos.current = hist.current.length;
    ws.current.send(cmd);
    setLine("");
  }

  function onKey(e) {
    if (e.key === "ArrowUp" && hist.current.length) {
      e.preventDefault();
      pos.current = Math.max(0, pos.current - 1);
      setLine(hist.current[pos.current] || "");
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      pos.current = Math.min(hist.current.length, pos.current + 1);
      setLine(hist.current[pos.current] || "");
    }
  }

  const live = status === "open";
  return (
    <div className="panel">
      <h2>Attacker terminal</h2>
      <div className="term" ref={box}>
        <pre>{out || (status === "idle" ? "Press Connect to open a session on the honeypot.\n" : "")}</pre>
      </div>
      <form className="inputrow" onSubmit={(e) => { e.preventDefault(); submit(line); }}>
        <input className="cmd" value={line} onChange={(e) => setLine(e.target.value)}
          onKeyDown={onKey} disabled={!live} maxLength={200}
          placeholder={live ? "type a command" : "not connected"}
          autoComplete="off" spellCheck={false} />
        {live
          ? <button type="submit">Send</button>
          : <button type="button" onClick={connect} disabled={status === "connecting"}>
              {status === "connecting" ? "Connecting..." : status === "closed" ? "Reconnect" : "Connect"}
            </button>}
      </form>
      <div className="chips">
        {SUGGESTIONS.map((c) => (
          <button key={c} type="button" className="ghost" disabled={!live} onClick={() => submit(c)}>{c}</button>
        ))}
      </div>
      {slow && <div className="note">Waking the server up. Free hosting can take up to a minute on the first visit.</div>}
    </div>
  );
}

function RiskBar({ n }) {
  return (
    <span className="bar" title={`risk ${n} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <i key={i} style={i <= n ? { background: n >= 4 ? "var(--red)" : n >= 3 ? "var(--amber)" : "var(--green)" } : undefined} />
      ))}
    </span>
  );
}

function Stat({ label, value, cls }) {
  return (
    <div className="stat"><b className={cls}>{value}</b><span>{label}</span></div>
  );
}

export default function Page() {
  const [state, dispatch] = useReducer(reduce, initial);
  const [conn, setConn] = useState("connecting");
  const [sel, setSel] = useState(null);
  const feedRef = useRef(null);
  useMonitor(dispatch, setConn);

  const current = sel ? state.sessions[sel] : state.sessions[state.order[0]];
  const feed = sel ? state.feed.filter((e) => e.sid === sel) : state.feed;
  const a = current?.analysis;
  const st = state.stats;
  const ttft = st?.avg_ttft_ms || 0;

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [feed.length]);

  return (
    <div className="wrap">
      <div className="top">
        <div>
          <h1>PhantomNet</h1>
          <div className="sub">
            A generative honeypot. Open a session on the left and act like an intruder.
            The fake Halcyon Freight server answers, and the analyst view on the right
            shows what a security team would see in real time.
          </div>
        </div>
        <span className="pill">
          <i className={`dot ${conn === "live" ? "on" : ""}`} />
          monitor: {conn}
        </span>
      </div>

      <div className="grid">
        <Terminal />

        <div className="panel">
          <h2>Analyst view</h2>
          <div className="stats">
            <Stat label="sessions" value={st?.sessions ?? 0} />
            <Stat label="active now" value={st?.active ?? 0} />
            <Stat label="commands" value={st?.commands ?? 0} />
            <Stat label="avg LLM time to first token"
              value={ttft ? `${ttft} ms` : "n/a"}
              cls={ttft ? (ttft < 500 ? "good" : "warn") : undefined} />
          </div>

          <div className="chipbar">
            <button className={`chip ${sel === null ? "sel" : ""}`} onClick={() => setSel(null)}>All</button>
            {state.order.map((sid) => {
              const s = state.sessions[sid];
              return (
                <button key={sid} className={`chip ${sel === sid ? "sel" : ""}`} onClick={() => setSel(sid)}>
                  <i className={`dot ${s.active ? "on" : ""}`} /> {sid} · {s.ip} · {s.count} cmds
                </button>
              );
            })}
          </div>

          {a ? (
            <>
              <div className="row"><span>Skill</span><b className={`skill ${a.skill}`}>{a.skill}</b></div>
              <div className="row"><span>Likely goal</span><b>{a.goal.replace(/_/g, " ")}</b></div>
              <div className="row"><span>Risk</span><RiskBar n={a.risk} /></div>
              <p className="summary">{a.summary}</p>
              <div className="muted small">
                Based on {a.n} commands, scored by {a.source === "llm" ? "the LLM" : "rules"}
              </div>
            </>
          ) : (
            <p className="muted small">
              No analysis yet. It runs after every 5 commands and when a session ends.
            </p>
          )}

          <div className="feed" ref={feedRef}>
            {feed.length === 0 && <p className="muted small">Waiting for commands...</p>}
            {feed.map((e, i) => (
              <div className="ev" key={`${e.ts}-${i}`}>
                <div className="evhead">
                  <span className="sid">{e.sid}</span>
                  <span className="cmd-text">$ {e.cmd}</span>
                  <span className={`tag ${e.llm ? "llm" : "tpl"}`}>
                    {e.llm ? `LLM${e.ttft_ms != null ? ` ${e.ttft_ms} ms` : ""}` : "template"}
                  </span>
                </div>
                <pre className="evout">{e.output}{e.truncated ? "\n... (truncated)" : ""}</pre>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="foot">
        All companies, people, hosts and credentials shown are fictional. Commands are never executed;
        a simulator answers them.
      </div>
    </div>
  );
}