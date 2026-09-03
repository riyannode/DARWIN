"use client";
import { useState } from "react";
import { apiRequest, csrfHeaders } from "../lib/api";

export function MandateForm() {
  const [status, setStatus] = useState("");
  async function save(formData: FormData) {
    setStatus("Saving mandate version…");
    try { await apiRequest("/api/agent/mandate", { method: "PUT", headers: csrfHeaders(), body: JSON.stringify({ assets: formData.get("assets"), entry_rules: formData.get("entry_rules"), sizing_rules: formData.get("sizing_rules"), exit_rules: formData.get("exit_rules") }) }); setStatus("Mandate version saved."); } catch (error) { setStatus(error instanceof Error ? error.message : "Save failed"); }
  }
  return <form action={save} className="form-stack"><label>Assets and universe<textarea name="assets" required /></label><label>Entry rules<textarea name="entry_rules" required /></label><label>Sizing rules<textarea name="sizing_rules" required /></label><label>Exit rules<textarea name="exit_rules" required /></label><button className="button primary" type="submit">Save mandate version</button>{status && <p className="form-status" role="status">{status}</p>}</form>;
}
