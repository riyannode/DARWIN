"use client";

import { useCallback, useEffect, useState } from "react";
import { OhlcvChart } from "../../components/ohlcv-chart";
import { apiRequest } from "../../lib/api";
import { showcaseSchema, type ShowcaseData, type ShowcaseRun, type ShowcaseRunSummary } from "../../lib/schemas";

function confidence(value: string | null | undefined): string {
  return value ? `${Math.round(Number(value) * 100)}%` : "—";
}

function DecisionBadge({ action }: { action: string | null | undefined }) {
  return action ? <span className={`decision-badge ${action.toLowerCase()}`}>{action}</span> : <span className="state-pill">NO DECISION</span>;
}

function Timestamp({ value }: { value: string | null | undefined }) {
  return <>{value ? new Date(value).toLocaleString() : "Not available"}</>;
}

function Factors({ run }: { run: ShowcaseRun }) {
  return <div className="factor-grid">
    <div><span className="eyebrow">SUPPORTING FACTORS</span><ul>{run.supportingFactors.length ? run.supportingFactors.map((factor) => <li key={factor}>{factor}</li>) : <li>None recorded</li>}</ul></div>
    <div><span className="eyebrow">RISK FACTORS</span><ul>{run.riskFactors.length ? run.riskFactors.map((factor) => <li key={factor}>{factor}</li>) : <li>None recorded</li>}</ul></div>
  </div>;
}

function RunRow({ run }: { run: ShowcaseRunSummary }) {
  return <div className="showcase-run-row">
    <div><strong>{run.decision.pair ?? "No pair"}</strong><span>{run.trigger} · <Timestamp value={run.completedAt} /></span></div>
    <div><DecisionBadge action={run.decision.action} /><span className="feed-outcome">{run.systemOutcome}</span></div>
  </div>;
}

export default function ShowcasePage() {
  const [data, setData] = useState<ShowcaseData | null>(null);
  const [status, setStatus] = useState("");

  const load = useCallback(async () => {
    const value = showcaseSchema.parse(await apiRequest<unknown>("/api/showcase"));
    return value;
  }, []);

  useEffect(() => {
    let mounted = true;
    const refresh = () => {
      void load()
        .then((value) => {
          if (!mounted) return;
          setData(value);
          setStatus("");
        })
        .catch((error: unknown) => {
          if (mounted) setStatus(error instanceof Error ? error.message : "Public showcase unavailable");
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [load]);

  const latest = data?.latestDecision;
  const history = latest?.evidence.selectedPair.marketHistory ?? {};
  return <div className="page showcase-page">
    <section className="live-disclosure" role="alert">
      <div><span className="live-label">LIVE MARKET SHOWCASE</span><strong>Real evidence, read-only judging surface</strong></div>
      <p>DEMO_MODE=false · Real model inference · Real Binance market evidence · Financial writes disabled</p>
    </section>
    <div className="page-heading showcase-heading">
      <div><p className="eyebrow">PUBLIC PROOF / NO OWNER LOGIN</p><h1>Watch the decision boundary.</h1><p className="hero-copy">DARWIN runs the production decision pipeline, persists its evidence, and stops before any financial mutation. This page exposes the stored product evidence only.</p></div>
      <div className="showcase-stamp"><span>SAFE-LIVE MODE</span><strong>Reads live. Writes off.</strong></div>
    </div>
    {status && <div className="notice warning" role="status">{status}</div>}
    {data && <>
      <section className="showcase-runtime-grid">
        <article className="panel"><p className="eyebrow">RUNTIME</p><h2>{data.showcaseState === "AVAILABLE" ? "Available" : "Stale"}</h2><p className="muted">Agent: <strong>{data.agentState}</strong> · Execution mode: <strong>{data.executionMode}</strong></p><p className="panel-note">Financial writes: <strong>DISABLED</strong> · Emergency stop: {data.emergencyStop ? "ACTIVE" : "not active"}</p></article>
        <article className="panel"><p className="eyebrow">FRESHNESS</p><h2>{data.freshness}</h2><p className="muted">Last decision: <Timestamp value={data.lastDecisionAt} /></p><p className="panel-note">Last market evidence: <Timestamp value={data.lastEvidenceAt} />{data.staleReason ? ` · ${data.staleReason}` : ""}</p></article>
      </section>
      {!latest ? <section className="panel"><h2>No completed scheduled decision</h2><p className="muted">The public surface does not fall back to synthetic data. Start the configured production worker to publish a real decision.</p></section> : <>
        <section className="panel showcase-decision-panel">
          <div className="panel-heading"><div><p className="eyebrow">LATEST REAL DECISION</p><h2><DecisionBadge action={latest.decision.action} /> {latest.decision.pair ?? "No selected pair"}</h2></div><span className="state-pill">{confidence(latest.decision.confidence)} confidence</span></div>
          <p className="decision-rationale">{latest.decision.rationale ?? latest.rationale ?? "No stored decision rationale."}</p>
          <Factors run={latest} />
          <div className="showcase-meta"><span>Trigger <strong>{latest.trigger}</strong></span><span>Completed <strong><Timestamp value={latest.completedAt} /></strong></span><span>Model <strong>{latest.model}</strong></span></div>
        </section>
        <section className="showcase-two-column">
          <main className="showcase-main">
            <section className="panel"><div className="panel-heading"><div><p className="eyebrow">MARKET SCAN EVIDENCE</p><h2>Configured → allowed → effective</h2></div><span className="state-pill">{latest.evidence.pairSelection.candidateSymbols.length} candidates</span></div><div className="universe-steps"><div><span>Configured universe</span><strong>{data.configuredUniverse.join(" · ") || "Not available"}</strong></div><div><span>Allowed symbols</span><strong>{data.allowedSymbols.join(" · ") || "Not available"}</strong></div><div><span>Effective universe</span><strong>{data.effectiveUniverse.join(" · ") || "Not available"}</strong></div></div><div className="candidate-row"><span className="eyebrow">CANDIDATE SYMBOLS</span>{latest.evidence.pairSelection.candidateSymbols.map((symbol) => <span className={symbol === latest.evidence.pairSelection.selectedPair ? "candidate selected" : "candidate"} key={symbol}>{symbol}{symbol === latest.evidence.pairSelection.selectedPair ? " · selected" : ""}</span>)}</div>{Object.keys(latest.evidence.pairSelection.candidateFailures).length > 0 && <p className="panel-note">Excluded candidate reads are retained by symbol: {Object.entries(latest.evidence.pairSelection.candidateFailures).map(([symbol, error]) => `${symbol} (${error})`).join(" · ")}</p>}</section>
            <section className="panel"><div className="panel-heading"><div><p className="eyebrow">SELECTED-PAIR EVIDENCE</p><h2>{latest.evidence.selectedPair.selectedPair ?? "No selected pair"}</h2></div><span className="state-pill">15m · 1h · 4h</span></div><OhlcvChart history={history} live /><div className="showcase-market"><span>Stored ticker</span><strong>{latest.evidence.selectedPair.market.price ? `${latest.evidence.selectedPair.market.price} ${latest.evidence.selectedPair.market.symbol ?? ""}` : "Not available"}</strong></div></section>
            <section className="panel"><div className="panel-heading"><div><p className="eyebrow">DETERMINISTIC AUTHORIZATION</p><h2>Policy: {latest.policy.result}</h2></div><span className={latest.policy.result === "PASS" ? "state-pill pass" : "state-pill fail"}>{latest.policy.reasonCode ?? "Recorded"}</span></div><p className="mandate-quote">{data.mandate ? `“${data.mandate}”` : "No public mandate text is stored."}</p><div className="showcase-outcome"><div><span>System outcome</span><strong>{latest.systemOutcome}</strong></div><div><span>Reason</span><strong>{latest.reason ?? latest.policy.reason ?? "None recorded"}</strong></div></div></section>
          </main>
          <aside className="showcase-sidebar"><section className="panel"><p className="eyebrow">RECENT REAL DECISIONS</p><h2>Scheduled history</h2><div className="showcase-run-list">{data.recentDecisions.map((run) => <RunRow run={run} key={run.id} />)}</div><p className="panel-note">Only completed SCHEDULED and RUN_ONCE decisions appear here. Audit events and order events are excluded.</p></section><section className="panel"><p className="eyebrow">WHAT THIS PROVES</p><ul className="demo-proof"><li>Real model decision persistence</li><li>Real public Binance market evidence</li><li>Candidate scan and pair selection evidence</li><li>Deterministic policy authorization</li><li>Safe-live financial write closure</li></ul><p className="panel-note"><strong>Does not claim:</strong> funded trading or a Binance order.</p></section></aside>
        </section>
      </>}
    </>}
  </div>;
}
