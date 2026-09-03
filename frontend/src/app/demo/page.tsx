import Link from "next/link";

export default function DemoPage() { return <div className="page demo-page"><p className="eyebrow">DEMO / READ-ONLY EVIDENCE</p><h1>Evidence, without exposure.</h1><p className="hero-copy">This optional view is intentionally empty until a real run is exported with sensitive account fields removed.</p><Link href="/activity" className="button secondary">View activity timeline</Link></div>; }
