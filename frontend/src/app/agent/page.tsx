"use client";

import { useCallback, useEffect, useState } from "react";
import { MandateForm } from "../../components/mandate-form";
import { apiRequest, csrfHeaders } from "../../lib/api";
import { agentSchema, type AgentData } from "../../lib/schemas";

const modes = ["HUMAN_APPROVAL", "AUTO_BOUNDED"] as const;
type Mode = (typeof modes)[number];

export default function AgentPage() {
  const [agent, setAgent] = useState<AgentData | null>(null);
  const [status, setStatus] = useState("");

  const loadAgent = useCallback(async () => {
    const value = await apiRequest<unknown>("/api/agent");
    return agentSchema.parse(value);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setAgent(await loadAgent());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Live state unavailable");
    }
  }, [loadAgent]);

  useEffect(() => {
    let mounted = true;
    void loadAgent()
      .then((value) => {
        if (mounted) setAgent(value);
      })
      .catch((error: unknown) => {
        if (mounted) setStatus(error instanceof Error ? error.message : "Live state unavailable");
      });
    return () => { mounted = false; };
  }, [loadAgent]);

  async function setMode(mode: Mode) {
    setStatus("Updating authority…");
    try {
      await apiRequest("/api/agent/mode", {
        method: "PUT",
        headers: csrfHeaders(),
        body: JSON.stringify({ mode }),
      });
      await refresh();
      setStatus(`Mode set to ${mode}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Update failed");
    }
  }

  async function act(path: "/api/agent/start" | "/api/agent/stop" | "/api/agent/run-once") {
    setStatus("Working…");
    try {
      const result = await apiRequest<{ state?: string; runId?: string }>(path, {
        method: "POST",
        headers: csrfHeaders(),
      });
      await refresh();
      setStatus(result.runId ? `Run completed: ${result.state ?? "recorded"}.` : `Agent ${path.split("/").pop()} completed.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Agent action failed");
    }
  }

  return <div className="page"><div className="page-heading"><div><p className="eyebrow">AGENT / MANDATE</p><h1>Give it a mandate.</h1><p className="hero-copy">DARWIN monitors and decides continuously. HUMAN_APPROVAL routes each actionable intent through operator approval and Codex Agent OS; AUTO_BOUNDED runs the same policy and revalidation flow through the bounded Binance Spot API.</p></div><div className="agent-state"><span className="signal-dot" />{agent?.state ?? "Not connected"}</div></div><section className="two-column"><article className="panel"><div className="panel-heading"><div><p className="eyebrow">TRADING MANDATE + EXECUTION POLICY</p><h2>What should it consider?</h2></div>{agent?.mandate !== null && agent?.mandate !== undefined && <span className="state-pill">Versioned</span>}</div><MandateForm key={agent?.mandate?.version ?? "new"} mandate={agent?.mandate ?? null} /></article><article className="panel"><p className="eyebrow">OPERATING MODE</p><h2>How much autonomy?</h2><div className="mode-list">{modes.map((mode) => <button key={mode} className={agent?.mode === mode ? "mode-option selected" : "mode-option"} onClick={() => setMode(mode)}><span>{mode}</span><small>{mode === "AUTO_BOUNDED" ? "Bounded autonomous execution through Binance Spot API" : "Supervised execution through Codex Agent OS"}</small></button>)}</div><div className="button-row agent-actions"><button className="button primary" onClick={() => act("/api/agent/start")}>Start agent</button><button className="button secondary" onClick={() => act("/api/agent/run-once")}>Run once</button><button className="button secondary" onClick={() => act("/api/agent/stop")}>Stop agent</button></div>{agent?.nextRunAt && <p className="panel-note">Next scheduled cycle: {new Date(agent.nextRunAt).toLocaleString()}</p>}{status && <p className="form-status" role="status">{status}</p>}<div className="callout"><strong>Deterministic execution policy.</strong><p>Allowed symbols, Max Per Trade, Max Concurrent Trades, budget, fresh account state, and exchange filters are backend authority. DARWIN cannot override them.</p><p><a className="text-link" href="/budget">Configure the 24h Trading Budget →</a></p></div></article></section></div>;
}
