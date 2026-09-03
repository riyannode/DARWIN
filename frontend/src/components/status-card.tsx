export function StatusCard({ label, value, note, tone = "neutral" }: { label: string; value: string; note: string; tone?: "neutral" | "good" | "warn" }) {
  return <article className={`status-card ${tone}`}><p className="eyebrow">{label}</p><strong>{value}</strong><p className="muted">{note}</p></article>;
}
