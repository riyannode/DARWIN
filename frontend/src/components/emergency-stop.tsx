"use client";

import { useState } from "react";
import { apiRequest, csrfHeaders } from "../lib/api";

type BudgetResponse = {
  availableBudget: string | null;
  spentAmount: string | null;
};

export function EmergencyStop({
  active,
  onChanged,
}: {
  active: boolean;
  onChanged?: (active: boolean) => void;
}) {
  const [currentActive, setCurrentActive] = useState(active);
  const [status, setStatus] = useState("");

  async function stop() {
    if (!window.confirm("Enable emergency stop and request cancellation of open DarwinSpot orders?")) return;
    try {
      await apiRequest("/api/agent/emergency-stop", { method: "POST", headers: csrfHeaders() });
      setCurrentActive(true);
      onChanged?.(true);
      setStatus("Emergency stop enabled. Reconciliation is required.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Stop failed");
    }
  }

  async function reactivate() {
    try {
      const budget = await apiRequest<BudgetResponse>("/api/budget");
      const reviewed = window.confirm(
        `Review current limits before reactivation. Available Budget: ${budget.availableBudget ?? "Unavailable"}; Spent Amount: ${budget.spentAmount ?? "Unavailable"}. Reactivate the agent?`,
      );
      if (!reviewed) return;
      await apiRequest("/api/agent/reactivate", {
        method: "POST",
        headers: csrfHeaders(),
      });
      setCurrentActive(false);
      onChanged?.(false);
      setStatus("Emergency stop cleared. Agent remains stopped until started.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Reactivation failed");
    }
  }

  return <div className="stop-panel"><div><p className="eyebrow">OWNER CONTROL</p><strong>{currentActive ? "Emergency stop active" : "Stop new execution"}</strong><p className="muted">The stop blocks new submissions and requests cancellation of open agent orders.</p></div>{currentActive ? <button className="button secondary" onClick={reactivate}>Review and reactivate</button> : <button className="button danger" onClick={stop}>Emergency stop</button>}{status && <p role="status">{status}</p>}</div>;
}
