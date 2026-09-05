"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useState } from "react";
import { useEffect } from "react";
import { EmergencyStop } from "./emergency-stop";
import { apiRequest } from "../lib/api";
import { agentSchema } from "../lib/schemas";

const nav = [["/", "Overview"], ["/demo", "Demo"], ["/showcase", "Showcase"], ["/agent", "Agent"], ["/budget", "Budget"], ["/activity", "Activity"], ["/settings", "Settings"]] as const;

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isDemo = pathname === "/demo";
  const isShowcase = pathname === "/showcase";
  const [authStatus, setAuthStatus] = useState("");
  const [emergencyStop, setEmergencyStop] = useState<boolean | null>(null);
  useEffect(() => {
    if (isDemo || isShowcase) return;
    apiRequest<unknown>("/api/agent")
      .then((value) => setEmergencyStop(agentSchema.parse(value).emergencyStop))
      .catch(() => setEmergencyStop(null));
  }, [isDemo, isShowcase, pathname]);
  async function login(formData: FormData) {
    setAuthStatus("Signing in…");
    try {
      await apiRequest("/api/auth/login", { method: "POST", body: JSON.stringify({ password: formData.get("password") }) });
      window.location.reload();
    } catch (error) {
      setAuthStatus(error instanceof Error ? error.message : "Sign-in failed");
    }
  }
  return <div className={isShowcase ? "app-shell showcase-shell" : "app-shell"}>
    <aside className={isShowcase ? "sidebar showcase-public-nav" : "sidebar"}>
      <Link href="/" className="wordmark"><span className="wordmark-mark">D</span><span>DarwinSpot</span></Link>
      <p className="eyebrow">AUTONOMOUS SPOT OPERATOR</p>
      <nav aria-label="Primary navigation">{nav.map(([href, label]) => <Link key={href} href={href} className={pathname === href ? "nav-link active" : "nav-link"}>{label}</Link>)}</nav>
      {isDemo ? <div className="sidebar-login demo-sidebar-login"><strong>Zero credentials</strong><span className="muted">No Binance or LLM connection.</span></div> : isShowcase ? <div className="sidebar-login demo-sidebar-login"><strong>Public read-only</strong><span className="muted">No owner session is required to inspect stored live evidence.</span></div> : <form action={login} className="sidebar-login"><label>Owner session<input name="password" type="password" required aria-label="Owner password" /></label><button className="button secondary" type="submit">Sign in</button>{authStatus && <p className="form-status" role="status">{authStatus}</p>}</form>}
      <div className="sidebar-note"><span className="signal-dot" /> {isDemo ? "Synthetic judge walkthrough" : isShowcase ? "Public live showcase" : "Owner-operated"}<br />{isDemo ? "No financial writes" : isShowcase ? "Financial writes disabled" : "Binance Agent OS"}</div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div><p className="eyebrow">{isDemo ? "DEMO MODE / SYNTHETIC FIXTURE" : isShowcase ? "PUBLIC SHOWCASE / REAL MARKET EVIDENCE" : `CONTROL ROOM / ${pathname === "/" ? "OVERVIEW" : pathname.slice(1).toUpperCase()}`}</p><p className="muted">{isDemo ? "Deterministic synthetic evidence. Financial writes disabled." : isShowcase ? "Real model and market evidence. Financial writes disabled." : "Your agent can act. Your budget stays deterministic."}</p></div><Link href={isDemo ? "/demo" : isShowcase ? "/showcase" : "/settings"} className="connection-chip"><span className="status-dot" /> {isDemo ? "DEMO MODE" : isShowcase ? "READ-ONLY" : "Connection"}</Link></header>
      {children}
      {!isDemo && !isShowcase && emergencyStop !== null && <div className="global-stop"><EmergencyStop active={emergencyStop} onChanged={setEmergencyStop} /></div>}
    </main>
  </div>;
}
