"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Nav from "../../Nav";
import "../../site.css";

const API = (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000").replace(/^ws/, "http");

export default function Replay() {
  const { sid } = useParams();
  const [events, setEvents] = useState(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    fetch(`${API}/api/sessions/${sid}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setEvents(d.events))
      .catch((s) => setError(s === 404 ? "Session not found. It may have expired." : "Could not reach the server."));
  }, [sid]);

  const cmds = (events || []).filter((e) => e.type === "command");
  const start = (events || []).find((e) => e.type === "session_start");
  const a = [...(events || [])].reverse().find((e) => e.type === "analysis");

  async function copy() {
    try { await navigator.clipboard.writeText(location.href); setToast("Link copied"); } catch { setToast(location.href); }
    setTimeout(() => setToast(""), 2500);
  }

  return (
    <>
      <Nav />
      <div className="wrap">
        <div className="top">
          <div>
            <h1>Session replay <span className="sid">{sid}</span></h1>
            <div className="sub">{start ? `${new Date(start.ts * 1000).toLocaleString()} · from ${start.ip} · ${cmds.length} commands` : "Loading..."}</div>
          </div>
          <div>
            <button className="btn sm" onClick={copy}>Copy link</button>
            <Link className="btn sm alt" href="/demo">Try it yourself</Link>
          </div>
        </div>
        {error && <div className="err">{error}</div>}
        {a && (
          <div className="panel" style={{ marginBottom: 16 }}>
            <h2>Analyst verdict</h2>
            <div className="row"><span>Skill</span><b className={`skill ${a.skill}`}>{a.skill}</b></div>
            <div className="row"><span>Likely goal</span><b>{a.goal.replace(/_/g, " ")}</b></div>
            <p className="summary">{a.summary}</p>
          </div>
        )}
        <div className="panel tl">
          <h2>Timeline</h2>
          {cmds.map((e, i) => (
            <div className="ev" key={i}>
              <div className="evhead">
                <span className="cmd-text">$ {e.cmd}</span>
                <span className={`tag ${e.llm ? "llm" : "tpl"}`}>{e.llm ? "LLM" : "template"}</span>
              </div>
              <pre className="evout">{e.output}{e.truncated ? "\n... (truncated)" : ""}</pre>
            </div>
          ))}
        </div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}