import { NextRequest, NextResponse } from 'next/server';
import { restGet, restUpdate } from '@/lib/postgres';
import { getStrategyDefaults, mergeConfig, StrategyConfig } from '@/lib/strategy-defaults';
import { STRATEGY_META } from '@/lib/strategy-meta';

interface RouteContext {
  params: Promise<{ name: string }>;
}

/**
 * GET /api/strategies/[name]/config
 * Returns { defaults, overrides, merged } for a strategy.
 */
export async function GET(_req: NextRequest, context: RouteContext) {
  const { name } = await context.params;

  if (!STRATEGY_META[name]) {
    return NextResponse.json({ error: `Unknown strategy: ${name}` }, { status: 404 });
  }

  try {
    const defaults = getStrategyDefaults(name);

    // Read overrides from Supabase deepstack_strategy_status.config
    const rows = await restGet<{ config: StrategyConfig | null }>(
      'deepstack_strategy_status',
      `name=eq.${name}&select=config`
    );
    const overrides = rows[0]?.config ?? null;
    const merged = mergeConfig(defaults, overrides);

    return NextResponse.json({ defaults, overrides, merged });
  } catch (error) {
    console.error(`Failed to get config for ${name}:`, error);
    return NextResponse.json({ error: 'Failed to load strategy config' }, { status: 500 });
  }
}

/**
 * PATCH /api/strategies/[name]/config
 * Saves config overrides to Supabase.
 * Body: { overrides: Record<string, number | boolean | string> }
 * Pass { overrides: null } to reset to defaults.
 */
export async function PATCH(req: NextRequest, context: RouteContext) {
  const { name } = await context.params;

  if (!STRATEGY_META[name]) {
    return NextResponse.json({ error: `Unknown strategy: ${name}` }, { status: 404 });
  }

  try {
    const body = await req.json();
    const overrides: StrategyConfig | null = body.overrides ?? null;

    // Validate field names against configSchema
    if (overrides) {
      const meta = STRATEGY_META[name];
      const validKeys = new Set(meta.configSchema.map(f => f.key));
      for (const key of Object.keys(overrides)) {
        if (!validKeys.has(key)) {
          return NextResponse.json(
            { error: `Invalid config field: ${key}` },
            { status: 400 }
          );
        }
      }

      // Validate values against schema constraints
      for (const field of meta.configSchema) {
        const value = overrides[field.key];
        if (value === undefined) continue;

        if (field.type === 'number' && typeof value === 'number') {
          if (field.min !== undefined && value < field.min) {
            return NextResponse.json(
              { error: `${field.label} must be >= ${field.min}` },
              { status: 400 }
            );
          }
          if (field.max !== undefined && value > field.max) {
            return NextResponse.json(
              { error: `${field.label} must be <= ${field.max}` },
              { status: 400 }
            );
          }
        }

        if (field.type === 'boolean' && typeof value !== 'boolean') {
          return NextResponse.json(
            { error: `${field.label} must be a boolean` },
            { status: 400 }
          );
        }
      }
    }

    // Update Supabase
    await restUpdate(
      'deepstack_strategy_status',
      `name=eq.${name}`,
      { config: overrides }
    );

    // Return merged result
    const defaults = getStrategyDefaults(name);
    const merged = mergeConfig(defaults, overrides);

    return NextResponse.json({ defaults, overrides, merged });
  } catch (error) {
    console.error(`Failed to update config for ${name}:`, error);
    return NextResponse.json({ error: 'Failed to save strategy config' }, { status: 500 });
  }
}
