"use client";

import { useCallback, useEffect, useState } from "react";
import { OhlcvChart } from "../../components/ohlcv-chart";
import { apiRequest } from "../../lib/api";
import {
  demoScenarioSchema,
  demoScenarioSummarySchema,
  type DemoScenario,
  type DemoScenarioSummary,
} from "../../lib/schemas";

function confidence(value: string): string {
  return `${Math.round(Number(value) * 100)}%`;
}

function JsonEvidence({ value }: { value: unknown }) {
  return <pre className="evidence-json">{JSON.stringify(value, null, 2)}</pre>;
}

function DecisionBadge({ action }: { action: DemoScenario["decision"]["action"] }) {
  return <span className={`decision-badge ${action.toLowerCase()}`}>{action}</span>;
}

export default function DemoPage() {
  const [summaries, setSummaries] = useState<DemoScenarioSummary[]>([]);
  const [scenario, setScenario] = useState<DemoScenario | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [status, setStatus] = useState("");

  const loadScenario = useCallback(async (scenarioId: string) => {
    setSelectedId(scenarioId);
    try {
      const value = await apiRequest<unknown>(`/api/demo/scenarios/${encodeURIComponent(scenarioId)}`);
      setScenario(demoScenarioSchema.parse(value));
      setStatus("");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Demo scenario unavailable");
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    void apiRequest<unknown>("/api/demo/scenarios")
      .then((value) => {
        if (!mounted) return;
        const parsed = demoScenarioSummarySchema.array().parse(value);
        setSummaries(parsed);
        if (parsed[0]) void loadScenario(parsed[0].scenarioId);
      })
      .catch((error: unknown) => {
        if (mounted) setStatus(error instanceof Error ? error.message : "Demo mode unavailable");
      });
    return () => { mounted = false; };
  }, [loadScenario]);

  return (
    <div className="page demo-page">
      <section className="demo-disclosure" role="alert">
        <div><span className="demo-label">DEMO MODE</span><strong>Deterministic synthetic fixture</strong></div>
        <p>Synthetic Binance-format evidence · No LLM API call · No live Binance connection · Financial writes disabled</p>
      </section>
      <div className="page-heading demo-heading">
        <div>
          <p className="eyebrow">JUDGE WALKTHROUGH / BACKEND EVIDENCE</p>
          <h1>See the boundary hold.</h1>
          <p className="hero-copy">DARWIN receives one mandate, scans a configured universe, decides BUY/SELL/HOLD, and applies the same deterministic guardrails before any execution path.</p>
        </div>
        <div className="demo-stamp"><span>ZERO CREDENTIALS</span><strong>Synthetic, not live</strong></div>
      </div>
      {status && <div className="notice warning" role="status">{status}</div>}
      {scenario && (
        <>
          <section className="demo-summary-grid">
            <article className="panel demo-thesis">
              <p className="eyebrow">SELECTED SCENARIO</p>
              <h2>{scenario.title}</h2>
              <p className="muted">{scenario.description}</p>
              <div className="decision-line"><DecisionBadge action={scenario.decision.action} /><span>{scenario.decision.pair}</span><span className="confidence">{confidence(scenario.decision.confidence)} confidence</span></div>
            </article>
            <article className="panel outcome-card">
              <p className="eyebrow">SYSTEM OUTCOME</p>
              <strong className="outcome-value">{scenario.systemOutcome}</strong>
              <span className="outcome-reason">{scenario.systemReason}</span>
              <p className="panel-note">Model decision and system outcome are separate. A valid demo BUY is never displayed as executed.</p>
            </article>
          </section>
          <div className="demo-layout">
            <main className="demo-main">
              <section className="panel">
                <div className="panel-heading"><div><p className="eyebrow">MODEL DECISION</p><h2><DecisionBadge action={scenario.decision.action} /> {scenario.decision.pair}</h2></div><span className="state-pill">{confidence(scenario.decision.confidence)} confidence</span></div>
                <p className="decision-rationale">{scenario.decision.rationale}</p>
                <div className="factor-grid"><div><span className="eyebrow">SUPPORTING FACTORS</span><ul>{scenario.decision.supporting_factors.map((factor) => <li key={factor}>{factor}</li>)}</ul></div><div><span className="eyebrow">RISK FACTORS</span><ul>{scenario.decision.risk_factors.map((factor) => <li key={factor}>{factor}</li>)}</ul></div></div>
                <p className="panel-note">Order type: {scenario.decision.order_type ?? "None"} · Quantity: {scenario.decision.quantity ?? "None"} · Price: {scenario.decision.price ?? "Market"}</p>
              </section>
              <section className="panel">
                <div className="panel-heading"><div><p className="eyebrow">PAIR SELECTION</p><h2>Configured → effective → selected</h2></div><span className="state-pill">{scenario.candidateScan.closedCandleCount} closed candles / interval</span></div>
                <div className="universe-steps"><div><span>Configured Universe</span><strong>{scenario.configuredUniverse.join(" · ")}</strong><small>Symbols DARWIN may monitor</small></div><div><span>Allowed Symbols</span><strong>{scenario.allowedSymbols.join(" · ")}</strong><small>Subset this mandate may trade</small></div><div><span>Effective Universe</span><strong>{scenario.effectiveUniverse.join(" · ")}</strong><small>Configured ∩ allowed ∩ valid Spot/USDT</small></div></div>
                <div className="candidate-row"><span className="eyebrow">CANDIDATE SCAN · {scenario.candidateScan.intervals.join(" + ")} × 10 CLOSED</span>{scenario.candidateScan.candidateSymbols.map((symbol) => <span className={symbol === scenario.candidateScan.selectedPair ? "candidate selected" : "candidate"} key={symbol}>{symbol}{symbol === scenario.candidateScan.selectedPair ? " · selected" : ""}</span>)}</div>
                <details className="evidence-details"><summary>Inspect candidate OHLCV payload</summary><JsonEvidence value={scenario.candidateScan.candidateHistory} /></details>
              </section>
              <section className="panel">
                <div className="panel-heading"><div><p className="eyebrow">SELECTED-PAIR EVIDENCE</p><h2>{scenario.selectedPairEvidence.selected_pair} deep scan</h2></div><span className="state-pill">15m · 1h · 4h × 48 CLOSED</span></div>
                <OhlcvChart history={scenario.selectedPairEvidence.market_history} />
                <div className="evidence-grid"><div><span>Current ticker</span><JsonEvidence value={scenario.selectedPairEvidence.market} /></div><div><span>Balances</span><JsonEvidence value={scenario.selectedPairEvidence.balances} /></div><div><span>Open orders</span><JsonEvidence value={scenario.selectedPairEvidence.open_orders} /></div><div><span>Symbol filters</span><JsonEvidence value={scenario.selectedPairEvidence.symbol_filters} /></div></div>
                <details className="evidence-details"><summary>Inspect recent activity evidence</summary><JsonEvidence value={scenario.selectedPairEvidence.recent_activity} /></details>
              </section>
              <section className="panel">
                <div className="panel-heading"><div><p className="eyebrow">GUARDRAIL EVALUATION</p><h2>Policy result: {scenario.policy.result}</h2></div><span className={scenario.policy.result === "PASS" ? "state-pill pass" : "state-pill fail"}>{scenario.policy.reasonCode ?? "No execution reason"}</span></div>
                <p className="mandate-quote">“{scenario.mandate}”</p>
                <div className="guardrail-grid">{scenario.policy.guardrails.map((guardrail) => <div className={`guardrail ${guardrail.result.toLowerCase()}`} key={guardrail.name}><div><strong>{guardrail.name}</strong><span>{guardrail.result}</span></div><small>{guardrail.detail}</small></div>)}</div>
                <div className="policy-stats"><div><span>Max Per Trade</span><strong>{scenario.policy.maxPerTrade} USDT</strong></div><div><span>24h Budget</span><strong>{scenario.policy.budgetAvailable} available / {scenario.policy.budgetTotal}</strong></div><div><span>Concurrent Trades</span><strong>0 / {scenario.policy.maxConcurrentTrades}</strong></div></div>
              </section>
            </main>
            <aside className="demo-sidebar">
              <section className="panel scenario-panel"><p className="eyebrow">DECISION FEED</p><h2>Three outcomes, one policy</h2><div className="scenario-list">{summaries.map((item) => <button type="button" className={selectedId === item.scenarioId ? "scenario-row selected" : "scenario-row"} key={item.scenarioId} onClick={() => void loadScenario(item.scenarioId)}><span><strong>{item.selectedPair}</strong><small>{item.title}</small></span><span><DecisionBadge action={item.decision} /><small>{item.reason}</small></span></button>)}</div><p className="panel-note">Feed rows are returned by the demo backend. Reloading recomputes the same fixture result.</p></section>
              <section className="panel"><p className="eyebrow">TRADING MANDATE</p><h2>Capital protection first.</h2><p className="muted">{scenario.mandate}</p><div className="mode-explain"><div><strong>AUTO_BOUNDED</strong><span>Autonomous live execution through the backend Binance Spot API.</span></div><div><strong>HUMAN_APPROVAL</strong><span>Supervised execution through the Codex + Binance Agent OS MCP path.</span></div></div></section>
              <section className="panel demo-proof"><p className="eyebrow">WHAT THIS PROVES</p><ul><li>Mandate and effective-universe behavior</li><li>Typed decision schema and rationale</li><li>Real deterministic policy enforcement</li><li>Budget and concurrency evaluation</li><li>Auditable product presentation</li></ul><p className="panel-note"><strong>Does not prove:</strong> live OpenAI inference, Binance authentication, or live order execution.</p></section>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
