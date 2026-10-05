import Link from "next/link";

export default function Nav() {
  return (
    <div className="nav">
      <Link href="/" className="brand"><i />PhantomNet</Link>
      <div>
        <Link className="link" href="/demo">Live demo</Link>
        <a className="link" href="https://github.com/kvaishnav88/PhantomNet">GitHub</a>
      </div>
    </div>
  );
}