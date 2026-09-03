"use client";

import { useState } from "react";
import { apiRequest, csrfHeaders } from "../lib/api";
import { activityDetailSchema, type ActivityDetail } from "../lib/schemas";

type ActivityItem = {
  id: string;
  type: string;
  state: string;
  timestamp: string;
  pair?: string;
  trigger?: string;
  budgetResult?: string;
  binanceOrderId?: string | null;
};

function detailValue(value: string | null | undefined): string {
  return value ?? "Not returned by Binance or unavailable";
}

function evidenceText(evidence: unknown): string {
  if (typeof evidence === "string") return evidence;
  return JSON.stringify(evidence ?? null, null, 2);
}

export function ActivityTimeline({ items, onChanged }: { items: ActivityItem[]; onChanged?: () => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, ActivityDetail>>({});
  const [status, setStatus] = useState("");

  async function toggle(item: ActivityItem) {
    setStatus("");
    if (expanded === item.id) {
      setExpanded(null);
      return;
    }
    setExpanded(item.id);
    if (details[item.id]) return;
    try {
      const response = await apiRequest<unknown>(`/api/activity/${encodeURIComponent(item.id)}`);
      const detail = activityDetailSchema.parse(response);
      setDetails((current) => ({ ...current, [item.id]: detail }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Activity detail unavailable");
    }
  }

  async function approve(item: ActivityItem) {
    setStatus("Submitting approved order…");
    try {
      const result = await apiRequest<{ state: string }>(`/api/orders/${encodeURIComponent(item.id)}/approve`, {
        method: "POST",
        headers: csrfHeaders(),
      });
      setStatus(`Approved order is ${result.state}.`);
      onChanged?.();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Approval failed");
    }
  }

  if (!items.length) return <div className="empty-state"><strong>No activity in this view.</strong><p className="muted">Connect Binance Agent OS and run one cycle. DarwinSpot never seeds fake trades.</p></div>;
  return <div className="timeline">{items.map((item) => { const detail = details[item.id]; return <article className="timeline-item" key={item.id}><span className="timeline-marker" /><div><button className="timeline-toggle" type="button" aria-expanded={expanded === item.id} onClick={() => void toggle(item)}><span className="timeline-head"><strong>{item.type}{item.trigger ? ` · ${item.trigger}` : ""}</strong><span className="state-pill">{item.state}</span></span><span className="muted">{item.pair ?? "Agent event"} · {new Date(item.timestamp).toLocaleString()}</span></button>{item.state === "PROPOSED" && <button className="button secondary timeline-action" type="button" onClick={() => void approve(item)}>Approve order</button>}{expanded === item.id && <ActivityDetailPanel detail={detail} fallback={item} />}</div></article>; })}{status && <p className="form-status" role="status">{status}</p>}</div>;
}

function ActivityDetailPanel({ detail, fallback }: { detail: ActivityDetail | undefined; fallback: ActivityItem }) {
  if (!detail) return <p className="muted">Loading evidence…</p>;
  return <div className="activity-detail"><dl><div><dt>State</dt><dd>{detailValue(detail.state ?? fallback.state)}</dd></div><div><dt>Mandate version</dt><dd>{detailValue(detail.mandateVersion)}</dd></div><div><dt>Budget version</dt><dd>{detailValue(detail.budgetVersion)}</dd></div><div><dt>Budget result</dt><dd>{detailValue(detail.budgetResult ?? fallback.budgetResult)}</dd></div><div><dt>Idempotency key</dt><dd>{detailValue(detail.idempotencyKey)}</dd></div><div><dt>Binance order id</dt><dd>{detailValue(detail.binanceOrderId ?? fallback.binanceOrderId)}</dd></div>{detail.pair && <div><dt>Order</dt><dd>{detail.side ?? ""} {detail.pair} · {detail.orderType ?? ""} · qty {detail.quantity ?? ""}</dd></div>}</dl>{detail.rationale && <p className="panel-note">{detail.rationale}</p>}{detail.events && detail.events.length > 0 && <div className="detail-events"><strong>State transitions and fills</strong>{detail.events.map((event) => <p className="muted" key={event.id}>{event.type} · {event.filledQuantity ?? "0"} qty · {event.filledNotional ?? "0"} quote · {new Date(event.observedAt).toLocaleString()}</p>)}</div>}<details><summary>Evidence timestamps and payload</summary><pre>{evidenceText(detail.evidence)}</pre></details></div>;
}
