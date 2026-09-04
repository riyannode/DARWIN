"use client";

import { useEffect, useState } from "react";
import { apiRequest, csrfHeaders } from "../../lib/api";
import { agentSchema, connectionSchema, type AgentData, type ConnectionData } from "../../lib/schemas";

type ConnectResponse = {
  state: string;
  transport?: string;
  mcpEndpoint: string;
  message: string;
  capabilities?: string[];
  authorizationUrl?: string;
};

export default function SettingsPage() {
  const [connection, setConnection] = useState<ConnectionData | null>(null);
  const [status, setStatus] = useState("");
  const [authorizationUrl, setAuthorizationUrl] = useState("");
  const [codexStatus, setCodexStatus] = useState<{ state: string; verification: string; tools: string[] } | null>(null);
  const [binanceApiStatus, setBinanceApiStatus] = useState<{ state: string; liveVerification: string } | null>(null);
  const [agent, setAgent] = useState<AgentData | null>(null);
  const [universeInput, setUniverseInput] = useState("");

  useEffect(() => {
    apiRequest<unknown>("/api/integrations/binance/status")
      .then((value) => setConnection(connectionSchema.parse(value)))
      .catch((error: unknown) =>
        setStatus(error instanceof Error ? error.message : "Connection state unavailable"),
      );
    apiRequest<{ state: string; verification: string; tools: string[] }>("/api/integrations/codex/status")
      .then(setCodexStatus)
      .catch(() => setCodexStatus(null));
    apiRequest<{ state: string; liveVerification: string }>("/api/integrations/binance-api/status")
      .then(setBinanceApiStatus)
      .catch(() => setBinanceApiStatus(null));
    apiRequest<unknown>("/api/agent")
      .then((value) => {
        const data = agentSchema.parse(value);
        setAgent(data);
        setUniverseInput(data.supportedSymbols.join(", "));
      })
      .catch(() => setAgent(null));
  }, []);

  async function saveUniverse(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const supportedSymbols = universeInput.split(",").map((value) => value.trim()).filter(Boolean);
    setStatus("Validating Spot symbols against Binance metadata…");
    try {
      const result = await apiRequest<{ supportedSymbols: string[] }>("/api/agent/universe", {
        method: "PUT",
        headers: csrfHeaders(),
        body: JSON.stringify({ supported_symbols: supportedSymbols }),
      });
      setUniverseInput(result.supportedSymbols.join(", "));
      setAgent((current) => current ? { ...current, supportedSymbols: result.supportedSymbols } : current);
      setStatus("Configured Spot universe saved.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Universe update failed");
    }
  }

  async function connect() {
    setStatus("Starting official Agent OS authorization…");
    setAuthorizationUrl("");
    try {
      const result = await apiRequest<ConnectResponse>(
        "/api/integrations/binance/connect",
        { method: "POST", headers: csrfHeaders() },
      );
      setConnection({
        state: result.state,
        accountReference: null,
        capabilities: result.capabilities ?? [],
      });
      setAuthorizationUrl(result.authorizationUrl ?? "");
      setStatus(`${result.message} Endpoint: ${result.mcpEndpoint}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Connect failed");
    }
  }

  async function disconnect() {
    try {
      await apiRequest("/api/integrations/binance/disconnect", {
        method: "POST",
        headers: csrfHeaders(),
      });
      setConnection({ state: "DISCONNECTED", accountReference: null, capabilities: [] });
      setAuthorizationUrl("");
      setStatus("Disconnected. New execution is blocked.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Disconnect failed");
    }
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">SETTINGS / BINANCE AGENT OS</p>
          <h1>Permission, made visible.</h1>
          <p className="hero-copy">
            DarwinSpot never asks for a Binance API key in the browser and never handles
            withdrawals or transfers.
          </p>
        </div>
      </div>
      <section className="panel connection-panel">
        <div>
          <p className="eyebrow">CONNECTION STATE</p>
          <h2>{connection?.state ?? "Not available"}</h2>
          <p className="muted">
            Account reference: {connection?.accountReference ?? "Redacted until a real connection exists"}
          </p>
        </div>
        <div className="button-row">
          <button className="button primary" onClick={connect}>Connect Binance Agent OS</button>
          <button className="button secondary" onClick={disconnect}>Disconnect</button>
        </div>
        {authorizationUrl && (
          <p className="form-status">
            <a className="text-link" href={authorizationUrl}>Open official Binance authorization</a>
          </p>
        )}
        {status && <p className="form-status" role="status">{status}</p>}
      </section>
      <section className="panel">
        <p className="eyebrow">SPOT TRADING UNIVERSE</p>
        <h2>Configured capability, not authorization.</h2>
        <p className="muted">Only an authenticated owner can change this persisted Spot/USDT list. Each symbol is checked against current Binance Spot metadata and required filters before saving.</p>
        <form className="inline-form" onSubmit={saveUniverse}>
          <label>Configured symbols<input value={universeInput} onChange={(event) => setUniverseInput(event.target.value)} placeholder="BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT" required /></label>
          <button className="button primary" type="submit">Save configured universe</button>
        </form>
        <p className="panel-note">Configured Universe: {agent?.supportedSymbols.join(" · ") || "Loading…"}</p>
        <p className="panel-note">Current Mandate Allowed Symbols: {agent?.mandate?.allowedSymbols.join(" · ") || "No mandate configured"}</p>
        <p className="muted">A configured symbol is not tradable until it is also present in a new/current mandate and passes fresh deterministic policy checks.</p>
      </section>
      <section className="panel">
        <p className="eyebrow">CODEX TRANSPORT</p>
        <h2>{codexStatus?.state ?? "UNAVAILABLE"}</h2>
        <p className="muted">Implementation: active · Authenticated live bridge: {codexStatus?.verification ?? "UNVERIFIED"}</p>
        {codexStatus?.tools.length ? <p className="panel-note">Discovered tools: {codexStatus.tools.join(", ")}</p> : <p className="empty-line">No authenticated Binance tools are shown. DARWIN remains safe to start, but writes stay blocked.</p>}
      </section>
      <section className="panel">
        <p className="eyebrow">BINANCE SPOT API TRANSPORT</p>
        <h2>{binanceApiStatus?.state ?? "NOT_CONFIGURED"}</h2>
        <p className="muted">Backend-only API credentials: {binanceApiStatus?.state === "READY" ? "configured" : "not configured"} · Live verification: {binanceApiStatus?.liveVerification ?? "UNVERIFIED"}</p>
        <p className="panel-note">AUTO_BOUNDED uses this narrow Spot transport for fresh reads, bounded submission, and reconciliation. Withdrawals, transfers, futures, margin, and options are not supported.</p>
      </section>
      <section className="panel">
        <p className="eyebrow">CAPABILITIES</p>
        <h2>Only the connected account decides availability.</h2>
        <p className="muted">
          Binance Agent OS supplies the authorized market, account, and trading tools. DarwinSpot
          stores only redacted capability metadata and encrypted session material.
        </p>
        {connection?.capabilities.length ? (
          <ul className="capability-list">
            {connection.capabilities.map((item) => <li key={item}>{item}</li>)}
          </ul>
        ) : (
          <p className="empty-line">No capabilities returned. No synthetic permissions are shown.</p>
        )}
      </section>
    </div>
  );
}
