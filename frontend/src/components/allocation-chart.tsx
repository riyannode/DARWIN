import { amount } from "../lib/format";

export function AllocationChart({ total, quoteAsset }: { total: string | null; quoteAsset: string | null }) {
  const label = total === null || quoteAsset === null ? "Allocation unavailable" : `${amount(total)} ${quoteAsset} live allocation`;
  return <div className="allocation-visual" aria-label={label}><div className="allocation-ring"><span>{total === null ? <>LIVE<br />DATA</> : <>{amount(total)}<br />{quoteAsset}</>}</span></div><p className="muted">{total === null ? "No synthetic allocation is shown." : "Valued from live balances and spot prices."}</p></div>;
}
