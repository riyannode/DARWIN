"use client";

import { useEffect, useState } from "react";
import { apiRequest, csrfHeaders } from "../../lib/api";
import { connectionSchema, type ConnectionData } from "../../lib/schemas";

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

  useEffect(() => {
    apiRequest<unknown>("/api/integrations/binance/status")
      .then((value) => setConnection(connectionSchema.parse(value)))
      .catch((error: unknown) =>
        setStatus(error instanceof Error ? error.message : "Connection state unavailable"),
      );
    apiRequest<{ state: string; verification: string; tools: string[] }>("/api/integrations/codex/status")
      .then(setCodexStatus)
      .catch(() => setCodexStatus(null));
  }, []);

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
        <p className="eyebrow">CODEX TRANSPORT</p>
        <h2>{codexStatus?.state ?? "UNAVAILABLE"}</h2>
        <p className="muted">Implementation: active · Authenticated live bridge: {codexStatus?.verification ?? "UNVERIFIED"}</p>
        {codexStatus?.tools.length ? <p className="panel-note">Discovered tools: {codexStatus.tools.join(", ")}</p> : <p className="empty-line">No authenticated Binance tools are shown. DARWIN remains safe to start, but writes stay blocked.</p>}
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
