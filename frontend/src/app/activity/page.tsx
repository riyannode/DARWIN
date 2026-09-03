"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityTimeline } from "../../components/activity-timeline";
import { apiRequest } from "../../lib/api";

type Activity = {
  id: string;
  type: string;
  state: string;
  timestamp: string;
  pair?: string;
  trigger?: string;
  budgetResult?: string;
  binanceOrderId?: string | null;
};

const filters = ["all", "decisions", "orders", "fills", "budget", "errors"] as const;
type Filter = (typeof filters)[number];

function belongsToFilter(item: Activity, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "decisions") return item.type === "decision";
  if (filter === "orders") return item.type === "order";
  if (filter === "fills") return item.type === "order_event" && item.state.toUpperCase().includes("FILL");
  if (filter === "budget") return item.state === "BUDGET_EXCEEDED" || item.budgetResult === "BUDGET_EXCEEDED";
  return item.state === "FAILED" || item.state.toUpperCase().includes("ERROR");
}

export default function ActivityPage() {
  const [items, setItems] = useState<Activity[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [status, setStatus] = useState("");

  const loadActivity = useCallback(async () => apiRequest<Activity[]>("/api/activity"), []);

  const reload = useCallback(async () => {
    try {
      setItems(await loadActivity());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Live activity unavailable");
    }
  }, [loadActivity]);

  useEffect(() => {
    let mounted = true;
    void loadActivity()
      .then((value) => {
        if (mounted) setItems(value);
      })
      .catch((error: unknown) => {
        if (mounted) setStatus(error instanceof Error ? error.message : "Live activity unavailable");
      });
    return () => { mounted = false; };
  }, [loadActivity]);

  const visibleItems = useMemo(() => items.filter((item) => belongsToFilter(item, filter)), [items, filter]);
  return <div className="page"><div className="page-heading"><div><p className="eyebrow">ACTIVITY / AUDIT TIMELINE</p><h1>Nothing disappears.</h1><p className="hero-copy">Decision, evidence, intent, exchange state, fill, cancellation, or rejection—one chronological record.</p></div></div>{status && <div className="notice warning" role="status">{status}</div>}<section className="panel"><div className="filter-row" role="group" aria-label="Activity filters">{filters.map((item) => <button className={filter === item ? "state-pill active-filter" : "state-pill"} aria-pressed={filter === item} type="button" key={item} onClick={() => setFilter(item)}>{item === "budget" ? "Budget rejections" : item[0].toUpperCase() + item.slice(1)}</button>)}</div><p className="panel-note">Expand an item to inspect evidence timestamps, versions, idempotency, exchange identifiers, and state transitions.</p><ActivityTimeline items={visibleItems} onChanged={() => void reload()} /></section></div>;
}
