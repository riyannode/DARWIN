import { z } from "zod";

export const agentSchema = z.object({
  mode: z.string(), state: z.string(), emergencyStop: z.boolean(), nextRunAt: z.string().nullable().optional(), mandate: z.unknown().nullable(), latestDecision: z.object({ id: z.string(), state: z.string(), decision: z.record(z.string(), z.unknown()).nullable(), rationale: z.string().nullable(), startedAt: z.string(), completedAt: z.string().nullable(), mandateVersion: z.string().nullable(), budgetVersion: z.string().nullable() }).nullable(),
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
  committedNotional: z.string().nullable().optional(),
  events: z.array(z.object({
    id: z.string(),
    type: z.string(),
    filledQuantity: z.string().nullable(),
    filledNotional: z.string().nullable(),
    observedAt: z.string(),
    exchangeTimestamp: z.string().nullable(),
  })).optional(),
});

export type AgentData = z.infer<typeof agentSchema>;
export type BudgetData = z.infer<typeof budgetSchema>;
export type ConnectionData = z.infer<typeof connectionSchema>;
export type PortfolioData = z.infer<typeof portfolioSchema>;
export type OpenOrder = z.infer<typeof openOrderSchema>;
export type ActivityDetail = z.infer<typeof activityDetailSchema>;
