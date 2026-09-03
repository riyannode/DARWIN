"use client";

import { useEffect, useState } from "react";
import { AllocationChart } from "../components/allocation-chart";
import { BudgetMeter } from "../components/budget-meter";
import { StatusCard } from "../components/status-card";
import { apiRequest } from "../lib/api";
import { time } from "../lib/format";
import {
  agentSchema,
  budgetSchema,
  portfolioSchema,
  type AgentData,
  type BudgetData,
  type PortfolioData,
} from "../lib/schemas";

export default function Overview() {
  const [agent, setAgent] = useState<AgentData | null>(null);
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([apiRequest<unknown>("/api/agent"), apiRequest<unknown>("/api/budget")])
      .then(([agentValue, budgetValue]) => {
        setAgent(agentSchema.parse(agentValue));
        setBudget(budgetSchema.parse(budgetValue));
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "Live backend unavailable"),
      );
    apiRequest<unknown>("/api/portfolio")
      .then((value) => setPortfolio(portfolioSchema.parse(value)))
      .catch(() => setPortfolio(null));
  }, []);

  return (
    <div className="page">
      <section className="hero">
        <div>
          <p className="eyebrow">OVERVIEW / LIVE ACCOUNT STATE</p>
          <h1>
            Let the agent act.
            <br />
            <em>Keep the boundary visible.</em>
          </h1>
          <p className="hero-copy">
            DarwinSpot connects one owner-operated agent to a dedicated Binance Agent OS
            allocation. Every decision has evidence. Every order has a state.
          </p>
        </div>
        <div className="hero-orbit"><AllocationChart total={portfolio?.allocation?.total ?? null} quoteAsset={portfolio?.allocation?.quoteAsset ?? null} /></div>
      </section>
      {error && (
        <div className="notice warning" role="status">
          <strong>Live state unavailable.</strong> {error}. Sign in and connect Binance Agent OS
          to load account-backed data.
        </div>
      )}
      {portfolio?.stale && (
        <div className="notice warning" role="status">
          <strong>Live data is stale.</strong> {portfolio.staleReason ?? "Refresh is required"}. New execution is blocked until current evidence returns.
        </div>
      )}
      <section className="status-grid">
        <StatusCard
          label="Agent state"
          value={agent?.state ?? "Not connected"}
          note={agent ? `Mode: ${agent.mode}` : "No synthetic state"}
          tone={agent?.emergencyStop ? "warn" : "neutral"}
        />
        <StatusCard
          label="Connection"
          value={portfolio?.connectionState ?? "Disconnected"}
          note="Binance Agent OS permissioned session"
        />
        <StatusCard
          label="Live balances"
          value={portfolio?.balances ? `${portfolio.balances.length} assets` : "Unavailable"}
          note={portfolio ? `Synced ${time(portfolio.syncedAt)}` : "Requires live balance snapshot"}
        />
        <StatusCard
          label="Agent allocation"
          value={portfolio?.allocation ? `${portfolio.allocation.total} ${portfolio.allocation.quoteAsset}` : "Unavailable"}
          note={portfolio?.allocation ? `Valued ${time(portfolio.allocation.asOf)}` : "Requires live balances and prices"}
        />
      </section>
      <section className="content-grid">
        <article className="panel">
          <div className="panel-heading">
            <div><p className="eyebrow">ROLLING 24-HOUR AUTHORITY</p><h2>Budget boundary</h2></div>
            <span className="status-label">Only two usage values</span>
          </div>
          <BudgetMeter available={budget?.availableBudget ?? null} spent={budget?.spentAmount ?? null} />
          <p className="panel-note">
            Spent Amount includes verified buy fills and quote value committed to open buy orders.
            Sells and cancellations do not consume it.
          </p>
        </article>
        <article className="panel">
          <p className="eyebrow">LATEST DECISION</p>
          <h2>{agent?.latestDecision ? String(agent.latestDecision.decision?.action ?? agent.latestDecision.state) : "No decision yet"}</h2>
          <p className="muted">{agent?.latestDecision?.rationale ?? "Decisions appear only after a real run with current market and account evidence."}</p>
          {agent?.latestDecision && <p className="panel-note">Run {agent.latestDecision.id} · mandate {agent.latestDecision.mandateVersion ?? "unavailable"} · budget {agent.latestDecision.budgetVersion ?? "unavailable"}</p>}
          <a className="text-link" href="/agent">Configure the mandate →</a>
        </article>
      </section>
      {portfolio?.balances && (
        <section className="panel" style={{ marginTop: "12px" }}>
          <p className="eyebrow">LIVE SPOT BALANCES</p>
          <h2>Account snapshot</h2>
          <div className="timeline">
            {portfolio.balances.map((balance) => (
              <div className="timeline-item" key={balance.asset}>
                <span className="timeline-marker" />
                <div className="timeline-head">
                  <strong>{balance.asset}</strong>
                  <span className="state-pill">free {balance.free} · locked {balance.locked}</span>
                </div>
              </div>
            ))}
          </div>
          <p className="panel-note">Balances are read from Binance Agent OS; no synthetic allocation is shown.</p>
        </section>
      )}
      {portfolio?.openOrders && (
        <section className="panel" style={{ marginTop: "12px" }}>
          <p className="eyebrow">OPEN ORDERS</p>
          <h2>{portfolio.openOrders.length ? `${portfolio.openOrders.length} live open orders` : "No live open orders"}</h2>
          {portfolio.openOrders.length > 0 && <div className="timeline">{portfolio.openOrders.map((order) => <div className="timeline-item" key={order.orderId}><span className="timeline-marker" /><div className="timeline-head"><strong>{order.symbol}</strong><span className="state-pill">{order.status}</span></div><p className="muted">Order {order.orderId} · executed {order.executedQuantity}</p></div>)}</div>}
          <p className="panel-note">Open orders are read from Binance Agent OS; no synthetic orders are shown.</p>
        </section>
      )}
    </div>
  );
}
