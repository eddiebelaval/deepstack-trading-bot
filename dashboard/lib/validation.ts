/**
 * Input Validation Schemas
 *
 * Zod schemas for validating API request inputs.
 * Prevents injection attacks and ensures data integrity.
 */

import { z } from 'zod';

// Common constraints
const MAX_LIMIT = 1000;
const MIN_LIMIT = 1;
const DEFAULT_LIMIT = 50;

// Status enums
export const TradeStatusSchema = z.enum(['pending', 'open', 'closed', 'cancelled']);
export const OpportunityStatusSchema = z.enum(['active', 'taken', 'expired', 'rejected', 'all']);
export const SideSchema = z.enum(['yes', 'no']);
export const SideUpperSchema = z.enum(['YES', 'NO']);
export const ActionSchema = z.enum(['buy', 'sell']);

// Trades API schemas
export const GetTradesQuerySchema = z.object({
  limit: z
    .string()
    .optional()
    .transform((val: string | undefined) => {
      const num = val ? parseInt(val, 10) : DEFAULT_LIMIT;
      return Math.min(Math.max(num, MIN_LIMIT), MAX_LIMIT);
    }),
  status: TradeStatusSchema.optional(),
});

export const CreateTradeSchema = z.object({
  market_ticker: z.string().min(1).max(100),
  side: z.string().min(1).max(10),
  action: z.string().min(1).max(10),
  contracts: z.number().int().positive().max(10000),
  entry_price_cents: z.number().int().min(1).max(99),
  fill_price_cents: z.number().int().min(1).max(99).nullable().optional(),
  exit_price_cents: z.number().int().min(1).max(99).nullable().optional(),
  pnl_cents: z.number().int().nullable().optional(),
  order_id: z.string().max(100).nullable().optional(),
  exit_order_id: z.string().max(100).nullable().optional(),
  status: z.string().max(20).optional().default('pending'),
  reasoning: z.string().max(1000).nullable().optional(),
  exit_reason: z.string().max(500).nullable().optional(),
  strategy: z.string().max(50).optional().default('mean_reversion'),
  session_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).nullable().optional(),
  metadata: z.string().nullable().optional(), // Stored as JSON string
});

export const UpdateTradeSchema = z.object({
  id: z.string().min(1).max(100),
  fill_price_cents: z.number().int().min(1).max(99).nullable().optional(),
  exit_price_cents: z.number().int().min(1).max(99).nullable().optional(),
  pnl_cents: z.number().int().nullable().optional(),
  exit_order_id: z.string().max(100).nullable().optional(),
  status: z.string().max(20).optional(),
  exit_reason: z.string().max(500).nullable().optional(),
  metadata: z.string().nullable().optional(), // Stored as JSON string
});

// Opportunities API schemas
export const GetOpportunitiesQuerySchema = z.object({
  status: OpportunityStatusSchema.optional(),
  limit: z
    .string()
    .optional()
    .transform((val: string | undefined) => {
      const num = val ? parseInt(val, 10) : DEFAULT_LIMIT;
      return Math.min(Math.max(num, MIN_LIMIT), MAX_LIMIT);
    }),
});

export const CreateOpportunitySchema = z.object({
  market_ticker: z.string().min(1).max(100),
  strategy: z.string().min(1).max(50),
  side: SideUpperSchema, // Must be 'YES' or 'NO'
  current_price_cents: z.number().int().min(1).max(99),
  target_price_cents: z.number().int().min(1).max(99),
  expected_profit_pct: z.number().min(-100).max(1000),
  confidence: z.number().min(0).max(1),
  status: z.enum(['active', 'taken', 'expired', 'rejected']).optional().default('active'),
  reasoning: z.string().max(1000).nullable().optional(),
});

export const UpdateOpportunitySchema = z.object({
  id: z.string().min(1).max(100),
  status: z.enum(['taken', 'expired', 'rejected']),
  trade_id: z.number().int().positive().optional(),
});

// Dashboard state schema
export const DashboardStateSchema = z.object({
  timestamp: z.string(),
  account: z.object({
    balance_cents: z.number().int(),
    daily_pnl_cents: z.number().int(),
    daily_pnl_percentage: z.number(),
    total_positions: z.number().int().min(0),
    available_balance_cents: z.number().int(),
  }),
  risk: z.object({
    daily_loss_limit_cents: z.number().int().min(0),
    daily_loss_used_cents: z.number().int(),
    max_position_size_cents: z.number().int().min(0),
    kelly_fraction: z.number().min(0).max(1),
    positions_at_risk: z.number().int().min(0),
    risk_percentage: z.number().min(0).max(100),
  }),
  strategies: z.array(z.object({
    name: z.string(),
    enabled: z.boolean(),
    active_positions: z.number().int().min(0),
    opportunities_found: z.number().int().min(0),
    last_scan: z.string().nullable(),
    status: z.string(),
  })),
});

// Helper function to validate and return result
export function validateRequest<T>(
  schema: z.ZodType<T>,
  data: unknown
): { success: true; data: T } | { success: false; error: string } {
  const result = schema.safeParse(data);
  if (result.success) {
    return { success: true, data: result.data };
  }
  return {
    success: false,
    error: result.error.issues.map((i: z.ZodIssue) => `${i.path.join('.')}: ${i.message}`).join(', '),
  };
}

// Bot command schema — per-command param validation
export const BotCommandTypeSchema = z.enum([
  'start', 'stop', 'pause', 'resume', 'toggle_strategy', 'update_risk',
  'force_close', 'switch_profile', 'set_mode', 'scan_now', 'place_trade',
  'set_poll_interval',
]);

// Commands that take no parameters
const NoParamsCommandSchema = z.object({
  command: z.enum(['start', 'stop', 'pause', 'resume', 'force_close', 'scan_now']),
  params: z.object({}).optional().default({}),
});

// Commands with typed parameters
const ToggleStrategyCommandSchema = z.object({
  command: z.literal('toggle_strategy'),
  params: z.object({
    strategy: z.string().min(1).max(50),
    enabled: z.boolean(),
  }),
});

const UpdateRiskCommandSchema = z.object({
  command: z.literal('update_risk'),
  params: z.object({
    kelly_fraction: z.number().min(0.1).max(1.0).optional(),
    max_position_size_cents: z.number().int().min(100).max(50000).optional(),
    daily_loss_limit_cents: z.number().int().min(1000).max(100000).optional(),
  }).refine(obj => Object.keys(obj).length > 0, { message: 'At least one risk parameter required' }),
});

const PlaceTradeCommandSchema = z.object({
  command: z.literal('place_trade'),
  params: z.object({
    ticker: z.string().min(1).max(100),
    side: z.enum(['yes', 'no', 'YES', 'NO']),
    contracts: z.number().int().positive().max(100),
  }),
});

const SwitchProfileCommandSchema = z.object({
  command: z.literal('switch_profile'),
  params: z.object({
    profile: z.string().min(1).max(50),
  }),
});

const SetModeCommandSchema = z.object({
  command: z.literal('set_mode'),
  params: z.object({
    dry_run: z.boolean(),
  }),
});

const SetPollIntervalCommandSchema = z.object({
  command: z.literal('set_poll_interval'),
  params: z.object({
    interval_seconds: z.number().int().min(15).max(300),
  }),
});

export const CreateBotCommandSchema = z.union([
  NoParamsCommandSchema,
  ToggleStrategyCommandSchema,
  UpdateRiskCommandSchema,
  PlaceTradeCommandSchema,
  SwitchProfileCommandSchema,
  SetModeCommandSchema,
  SetPollIntervalCommandSchema,
]);

// Bot config update schema (partial — only allow safe fields)
export const UpdateBotConfigSchema = z.object({
  mode: z.enum(['running', 'stopped', 'paused', 'dry_run']).optional(),
  poll_interval_seconds: z.number().int().min(15).max(300).optional(),
  max_position_size_cents: z.number().int().min(100).max(50000).optional(),
  daily_loss_limit_cents: z.number().int().min(1000).max(100000).optional(),
  kelly_fraction: z.number().min(0.1).max(1.0).optional(),
  profile: z.string().max(50).optional(),
  use_grok: z.boolean().optional(),
});

// Log entry creation schema
export const CreateLogEntrySchema = z.object({
  timestamp: z.string().optional(),
  level: z.enum(['DEBUG', 'INFO', 'WARNING', 'ERROR']).optional().default('INFO'),
  strategy: z.string().max(50).nullable().optional(),
  message: z.string().min(1).max(5000),
});

// Type exports
export type GetTradesQuery = z.infer<typeof GetTradesQuerySchema>;
export type CreateTrade = z.infer<typeof CreateTradeSchema>;
export type UpdateTrade = z.infer<typeof UpdateTradeSchema>;
export type GetOpportunitiesQuery = z.infer<typeof GetOpportunitiesQuerySchema>;
export type CreateOpportunity = z.infer<typeof CreateOpportunitySchema>;
export type UpdateOpportunity = z.infer<typeof UpdateOpportunitySchema>;
export type DashboardState = z.infer<typeof DashboardStateSchema>;
export type CreateBotCommand = z.infer<typeof CreateBotCommandSchema>;
export type UpdateBotConfig = z.infer<typeof UpdateBotConfigSchema>;
