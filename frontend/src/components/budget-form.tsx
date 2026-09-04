"use client";

import { useState } from "react";
import { apiRequest, csrfHeaders } from "../lib/api";

export function BudgetForm({ onSaved }: { onSaved?: () => void }) {
  const [status, setStatus] = useState("");

  async function save(formData: FormData) {
    setStatus("Saving budget version…");
    try {
      await apiRequest("/api/budget", {
        method: "PUT",
        headers: csrfHeaders(),
        body: JSON.stringify({ daily_budget: formData.get("daily_budget") }),
      });
      onSaved?.();
      setStatus("Budget version saved.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  return (
    <form action={save} className="inline-form">
      <label>
        24h Trading Budget
        <input
          name="daily_budget"
          inputMode="decimal"
          min="0.000000000001"
          step="any"
          required
        />
        <span className="muted">
          Maximum rolling BUY capital DARWIN may deploy over any 24-hour period.
        </span>
      </label>
      <button className="button primary" type="submit">
        Save budget
      </button>
      {status && <p className="form-status" role="status">{status}</p>}
    </form>
  );
}
