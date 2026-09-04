import { z } from "zod";

export const agentSchema = z.object({
  mode: z.enum(["HUMAN_APPROVAL", "AUTO_BOUNDED"]),
  state: z.string(),
  supportedSymbols: z.array(z.string()),
  emergencyStop: z.boolean(),
  nextRunAt: z.string().nullable().optional(),
  mandate: z.object({
    version: z.string(),
    tradingMandate: z.string(),
    allowedSymbols: z.array(z.string()),
    maxOrderNotional: z.string(),
    maxOpenActionableIntents: z.number(),
    createdAt: z.string(),
  }).nullable(),
  latestDecision: z.object({
    id: z.string(),
    state: z.string(),
    decision: z.record(z.string(), z.unknown()).nullable(),
    rationale: z.string().nullable(),
    startedAt: z.string(),
    completedAt: z.string().nullable(),
    mandateVersion: z.string().nullable(),
    budgetVersion: z.string().nullable(),
  }).nullable(),
});
export const budgetSchema = z.object({ dailyBudget: z.string().nullable(), availableBudget: z.string().nullable(), spentAmount: z.string().nullable() });
export const connectionSchema = z.object({ state: z.string(), accountReference: z.string().nullable(), capabilities: z.array(z.string()) });
export const openOrderSchema = z.object({
  orderId: z.string(),
  symbol: z.string(),
  status: z.string(),
  executedQuantity: z.string(),
  quoteNotional: z.string(),
  updatedAt: z.string(),
});
export const allocationSchema = z.object({
  quoteAsset: z.string(),
  total: z.string(),
  asOf: z.string(),
});
export const portfolioSchema = z.object({
  connectionState: z.string(),
  balances: z.array(z.object({ asset: z.string(), free: z.string(), locked: z.string() })).nullable(),
  allocation: allocationSchema.nullable(),
  openOrders: z.array(openOrderSchema).nullable(),
  openOrdersSyncedAt: z.string().nullable(),
  stale: z.boolean(),
  staleReason: z.string().nullable(),
  syncedAt: z.string().nullable(),
});
export const activityDetailSchema = z.object({
  id: z.string(),
  type: z.string(),
  trigger: z.string().optional(),
  decision: z.unknown().nullable().optional(),
  rationale: z.string().nullable().optional(),
  evidence: z.unknown().nullable().optional(),
  mandateVersion: z.string().nullable().optional(),
  budgetVersion: z.string().nullable().optional(),
  idempotencyKey: z.string().optional(),
  binanceOrderId: z.string().nullable().optional(),
  pair: z.string().optional(),
  side: z.string().optional(),
  orderType: z.string().optional(),
  quantity: z.string().optional(),
  quoteNotional: z.string().nullable().optional(),
  price: z.string().nullable().optional(),
  state: z.string().optional(),
  budgetResult: z.string().optional(),
  approvalState: z.string().nullable().optional(),
  approvalExpiresAt: z.string().nullable().optional(),
  notificationState: z.string().optional(),
  committedNotional: z.string().nullable().optional(),
  supportingFactors: z.array(z.string()).optional(),
  riskFactors: z.array(z.string()).optional(),
  confidence: z.string().optional(),
  revalidationEvidence: z.string().nullable().optional(),
  revalidationFailedReason: z.string().nullable().optional(),
  executionMode: z.enum(["HUMAN_APPROVAL", "AUTO_BOUNDED"]).optional(),
  executionTransport: z.string().optional(),
  authorizationSource: z.string().nullable().optional(),
  authorizedAt: z.string().nullable().optional(),
  confirmationRequestId: z.string().nullable().optional(),
  confirmationExpiresAt: z.string().nullable().optional(),
  approval: z.object({ id: z.string(), state: z.string(), expiresAt: z.string(), decidedAt: z.string().nullable(), decisionSource: z.string().nullable() }).nullable().optional(),
  events: z.array(z.object({
    id: z.string(),
    type: z.string(),
    filledQuantity: z.string().nullable(),
    filledNotional: z.string().nullable(),
    observedAt: z.string(),
    exchangeTimestamp: z.string().nullable(),
  })).optional(),
});

export const demoScenarioSummarySchema = z.object({
  scenarioId: z.string(),
  title: z.string(),
  description: z.string(),
  timestamp: z.string(),
  selectedPair: z.string(),
  decision: z.enum(["BUY", "SELL", "HOLD"]),
  confidence: z.string(),
  systemOutcome: z.enum(["EXECUTED", "PENDING", "SKIPPED", "FAILED"]),
  reason: z.string(),
  policy: z.string(),
});

const demoCandleSchema = z.object({
  open_time: z.string(),
  close_time: z.string(),
  open: z.string(),
  high: z.string(),
  low: z.string(),
  close: z.string(),
  volume: z.string(),
  quote_volume: z.string(),
});

const demoHistorySchema = z.object({
  symbol: z.string(),
  interval: z.enum(["15m", "1h", "4h"]),
  candles: z.array(demoCandleSchema),
});

export const demoScenarioSchema = z.object({
  mode: z.literal("DEMO_MODE"),
  scenarioId: z.string(),
  title: z.string(),
  description: z.string(),
  timestamp: z.string(),
  disclosure: z.object({
    deterministic: z.boolean(),
    recordedEvidence: z.boolean(),
    llmCall: z.boolean(),
    liveBinance: z.boolean(),
    financialWrites: z.boolean(),
  }),
  configuredUniverse: z.array(z.string()),
  allowedSymbols: z.array(z.string()),
  effectiveUniverse: z.array(z.string()),
  candidateScan: z.object({
    intervals: z.array(z.string()),
    closedCandleCount: z.number(),
    candidateSymbols: z.array(z.string()),
    candidateHistory: z.record(z.string(), z.record(z.string(), z.unknown())),
    selectedPair: z.string(),
    excludedCandidates: z.array(z.string()),
  }),
  selectedPairEvidence: z.object({
    selected_pair: z.string(),
    market: z.record(z.string(), z.unknown()),
    market_history: z.record(z.string(), demoHistorySchema),
    balances: z.record(z.string(), z.unknown()),
    open_orders: z.record(z.string(), z.unknown()),
    recent_activity: z.record(z.string(), z.unknown()),
    symbol_filters: z.record(z.string(), z.unknown()),
  }),
  mandate: z.string(),
  policy: z.object({
    allowedSymbols: z.array(z.string()),
    maxPerTrade: z.string(),
    budgetTotal: z.string(),
    budgetSpentOrReserved: z.string(),
    budgetAvailable: z.string(),
    maxConcurrentTrades: z.number(),
    emergencyStop: z.boolean(),
    result: z.string(),
    reason: z.string().nullable(),
    reasonCode: z.string().nullable(),
    guardrails: z.array(z.object({ name: z.string(), result: z.string(), detail: z.string() })),
  }),
  decision: z.object({
    action: z.enum(["BUY", "SELL", "HOLD"]),
    pair: z.string().nullable(),
    order_type: z.enum(["MARKET", "LIMIT"]).nullable(),
    side: z.enum(["BUY", "SELL"]).nullable(),
    quantity: z.string().nullable(),
    price: z.string().nullable(),
    rationale: z.string(),
    evidence: z.array(z.string()),
    confidence: z.string(),
    supporting_factors: z.array(z.string()),
    risk_factors: z.array(z.string()),
  }),
  systemOutcome: z.enum(["EXECUTED", "PENDING", "SKIPPED", "FAILED"]),
  systemReason: z.string(),
  intentCreated: z.boolean(),
  lifecycle: z.array(z.string()),
});

export type AgentData = z.infer<typeof agentSchema>;
export type BudgetData = z.infer<typeof budgetSchema>;
export type ConnectionData = z.infer<typeof connectionSchema>;
export type PortfolioData = z.infer<typeof portfolioSchema>;
export type OpenOrder = z.infer<typeof openOrderSchema>;
export type ActivityDetail = z.infer<typeof activityDetailSchema>;
export type DemoScenarioSummary = z.infer<typeof demoScenarioSummarySchema>;
export type DemoScenario = z.infer<typeof demoScenarioSchema>;
