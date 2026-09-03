export function BudgetMeter({ available, spent }: { available: string | null; spent: string | null }) {
  const availableValue = available === null ? Number.NaN : Number(available);
  const spentValue = spent === null ? Number.NaN : Number(spent);
  const total = availableValue + spentValue;
  const spentPercent = Number.isFinite(total) && total > 0
    ? Math.min(100, Math.max(0, (spentValue / total) * 100))
    : 0;
  return <div className="budget-meter"><div className="meter-track" aria-label={Number.isFinite(total) ? `${spentPercent.toFixed(1)} percent spent` : "Budget usage unavailable"}><span style={{ width: `${spentPercent}%` }} /></div><div className="meter-legend"><span>Available Budget <b>{available ?? "Unavailable"}</b></span><span>Spent Amount <b>{spent ?? "Unavailable"}</b></span></div></div>;
}
