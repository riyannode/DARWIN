"use client";

import { useState } from "react";
import { apiRequest, csrfHeaders } from "../lib/api";
import type { AgentData } from "../lib/schemas";

type MandateData = NonNullable<AgentData["mandate"]>;

type MandateFormProps = {
  mandate: MandateData | null;
};

export function MandateForm({ mandate }: MandateFormProps) {
  const [tradingMandate, setTradingMandate] = useState(mandate?.tradingMandate ?? "");
  const [allowedSymbols, setAllowedSymbols] = useState(mandate?.allowedSymbols.join(", ") ?? "");
  const [maxOrderNotional, setMaxOrderNotional] = useState(mandate?.maxOrderNotional ?? "");
  const [maxOpenActionableIntents, setMaxOpenActionableIntents] = useState(
    String(mandate?.maxOpenActionableIntents ?? 1),
  );
  const [status, setStatus] = useState("");

  async function save(formData: FormData) {
    setStatus("Saving mandate version…");
    try {
      await apiRequest("/api/agent/mandate", {
        method: "PUT",
        headers: csrfHeaders(),
        body: JSON.stringify({
          trading_mandate: formData.get("trading_mandate"),
          allowed_symbols: String(formData.get("allowed_symbols") ?? "")
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          max_order_notional: formData.get("max_order_notional"),
          max_open_actionable_intents: Number(formData.get("max_open_actionable_intents")),
        }),
      });
      setStatus("Mandate version saved.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  return (
    <form action={save} className="form-stack">
      <label>
        Trading Mandate
        <textarea
          name="trading_mandate"
          value={tradingMandate}
          onChange={(event) => setTradingMandate(event.target.value)}
          placeholder="Protect capital and prefer HOLD when evidence is unclear."
          required
        />
        <span className="muted">
          Describe the trading approach. DARWIN chooses pair, timing, side, size, and order type within the limits below.
        </span>
      </label>
      <label>
        Allowed Symbols
        <input
          name="allowed_symbols"
          value={allowedSymbols}
          onChange={(event) => setAllowedSymbols(event.target.value)}
          placeholder="BTCUSDT, ETHUSDT, SOLUSDT"
          required
        />
      </label>
      <label>
        Max Per Trade
        <input
          name="max_order_notional"
          value={maxOrderNotional}
          onChange={(event) => setMaxOrderNotional(event.target.value)}
          type="number"
          min="0.000000000001"
          step="0.000000000001"
          required
        />
        <span className="muted">Maximum USDT notional DARWIN may use for one trade.</span>
      </label>
      <label>
        Max Concurrent Trades
        <input
          name="max_open_actionable_intents"
          value={maxOpenActionableIntents}
          onChange={(event) => setMaxOpenActionableIntents(event.target.value)}
          type="number"
          min="1"
          max="100"
          step="1"
          required
        />
        <span className="muted">
          Maximum active trade workflows. Not an open-position limit.
        </span>
      </label>
      <button className="button primary" type="submit">
        Save mandate version
      </button>
      {status && <p className="form-status" role="status">{status}</p>}
    </form>
  );
}
