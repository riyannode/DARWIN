"use client";
import { useState } from "react";
import { apiRequest, csrfHeaders } from "../lib/api";

export function MandateForm() {
  const [status, setStatus] = useState("");
  async function save(formData: FormData) {
    setStatus("Saving mandate version…");
    try { await apiRequest("/api/agent/mandate", { method: "PUT", headers: csrfHeaders(), body: JSON.stringify({ assets: formData.get("assets"), entry_rules: formData.get("entry_rules"), sizing_rules: formData.get("sizing_rules"), exit_rules: formData.get("exit_rules"), allowed_symbols: String(formData.get("allowed_symbols") ?? "").split(",").map((value) => value.trim()), max_order_notional: formData.get("max_order_notional"), max_open_actionable_intents: Number(formData.get("max_open_actionable_intents")) }) }); setStatus("Mandate version saved."); } catch (error) { setStatus(error instanceof Error ? error.message : "Save failed"); }
  }
  return <form action={save} className="form-stack"><label>Assets and universe<textarea name="assets" required /></label><label>Entry rules<textarea name="entry_rules" required /></label><label>Sizing rules<textarea name="sizing_rules" required /></label><label>Exit rules<textarea name="exit_rules" required /></label><label>Allowed symbols<input name="allowed_symbols" placeholder="BTCUSDT, ETHUSDT" required /></label><label>Maximum order notional (USDT)<input name="max_order_notional" type="number" min="0.000000000001" step="0.000000000001" required /></label><label>Maximum open actionable intents<input name="max_open_actionable_intents" type="number" min="1" max="100" step="1" defaultValue="1" required /></label><button className="button primary" type="submit">Save mandate version</button>{status && <p className="form-status" role="status">{status}</p>}</form>;
}
