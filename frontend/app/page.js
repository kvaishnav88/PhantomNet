import Link from "next/link";
import Nav from "./Nav";
import "./site.css";

const STEPS = [
  ["🪤", "1. Lure", "An intruder lands on what looks like a real Ubuntu server at a freight company."],
  ["🧠", "2. Generate", "Python owns the filesystem. An LLM writes the messy details on demand, always consistent with the company's lore."],
  ["📡", "3. Watch", "Every command streams live to an analyst dashboard that scores the intruder's skill and goal."],
];
const FEATURES = [
  ["🗂️", "Consistent fake universe", "Same file, same bytes, every time. No contradictions an attacker can use to spot the fake."],
  ["⚡", "Hybrid speed", "Common commands answer instantly from templates. Only open-ended ones call the LLM."],
  ["🎯", "Behavioral analysis", "Skill level, likely goal and a risk score, from rules plus an LLM summary."],
  ["🔗", "Shareable replays", "Every session is stored. Copy a link and anyone can replay it step by step."],
  ["📥", "Export", "Download any session as JSON for your own analysis."],
  ["🛡️", "Abuse-proof", "Per-IP limits, session caps and a daily LLM budget keep the public demo safe."],
];
const ROWS = [
  ["Traffic redirection", "Direct connection to the honeypot", "iptables / eBPF"],
  ["Generative filesystem", "Simulated shell + virtual FS", "FUSE mount"],
  ["Context memory", "Per-session cache + stored logs", "Vector store"],
  ["LLM", "Groq in the cloud (Ollama supported)", "Local model"],
];

export default function Home() {
  return (
    <>
      <Nav />
      <div className="hero">
        <h1>The honeypot that <em>hallucinates</em> on purpose</h1>
        <p>PhantomNet turns LLM hallucination into a weapon. Intruders explore a fake company that is invented as they look, while a security analyst watches every move.</p>
        <Link className="btn" href="/demo">Try the live demo</Link>
        <a className="btn alt" href="https://github.com/kvaishnav88/PhantomNet">View on GitHub</a>
      </div>

      <div className="sec">
        <h2>How it works</h2>
        <div className="cards">
          {STEPS.map(([i, t, d]) => (
            <div className="card" key={t}><div className="ic">{i}</div><h3>{t}</h3><p>{d}</p></div>
          ))}
        </div>
      </div>

      <div className="sec">
        <h2>What you get</h2>
        <div className="cards">
          {FEATURES.map(([i, t, d]) => (
            <div className="card" key={t}><div className="ic">{i}</div><h3>{t}</h3><p>{d}</p></div>
          ))}
        </div>
      </div>

      <div className="sec">
        <h2>Simulated vs. real</h2>
        <p className="muted small">This is a scoped prototype. Here is exactly what is real and what is simulated.</p>
        <table className="cmp">
          <thead><tr><th>Concept</th><th>This demo</th><th>Production</th></tr></thead>
          <tbody>{ROWS.map((r) => <tr key={r[0]}>{r.map((c) => <td key={c}>{c}</td>)}</tr>)}</tbody>
        </table>
      </div>

      <div className="sec" style={{ textAlign: "center" }}>
        <Link className="btn" href="/demo">Open the demo</Link>
        <div className="foot">All companies, people, hosts and credentials are fictional. Commands are never executed.</div>
      </div>
    </>
  );
}