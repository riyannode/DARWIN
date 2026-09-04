"use client";

import { useCallback, useEffect, useState } from "react";
import { BudgetForm } from "../../components/budget-form";
import { BudgetMeter } from "../../components/budget-meter";
import { apiRequest } from "../../lib/api";
import { amount } from "../../lib/format";
import { budgetSchema, type BudgetData } from "../../lib/schemas";

export default function BudgetPage() {
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [status, setStatus] = useState("");

  const loadBudget = useCallback(async () => {
    const value = await apiRequest<unknown>("/api/budget");
    return budgetSchema.parse(value);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setBudget(await loadBudget());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Live budget unavailable");
    }
  }, [loadBudget]);

  useEffect(() => {
    let mounted = true;
    void loadBudget()
      .then((value) => {
        if (mounted) setBudget(value);
      })
      .catch((error: unknown) => {
        if (mounted) setStatus(error instanceof Error ? error.message : "Live budget unavailable");
      });
    return () => { mounted = false; };
  }, [loadBudget]);

  return <div className="page"><div className="page-heading"><div><p className="eyebrow">BUDGET / ROLLING 24 HOURS</p><h1>One boundary.<br /><em>Two visible numbers.</em></h1><p className="hero-copy">The agent may use any Available Budget in one or more Spot BUYs. SELLs and cancellations do not consume it.</p></div></div><section className="budget-hero"><div className="budget-number"><span>Available Budget</span><strong>{amount(budget?.availableBudget)}</strong><p className="muted">Available to the next valid buy</p></div><div className="budget-number accent"><span>Spent Amount</span><strong>{amount(budget?.spentAmount)}</strong><p className="muted">Verified fills + active BUY commitments</p></div></section><section className="panel"><p className="eyebrow">OWNER CONFIGURATION</p><h2>Set the rolling budget</h2><BudgetForm onSaved={() => void refresh()} /><BudgetMeter available={budget?.availableBudget ?? null} spent={budget?.spentAmount ?? null} />{status && <p className="form-status" role="status">{status}</p>}<p className="panel-note">Budget increases create a new version and require an authenticated owner action. If durable exchange-backed state is unavailable, DarwinSpot cannot submit a new buy.</p></section></div>;
}
