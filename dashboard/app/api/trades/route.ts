import { NextResponse } from 'next/server';
import { getRecentTrades, createTrade, updateTrade } from '@/lib/db-postgres';
import {
  GetTradesQuerySchema,
  CreateTradeSchema,
  UpdateTradeSchema,
} from '@/lib/validation';
import { Trade } from '@/lib/types';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const queryParams = Object.fromEntries(searchParams.entries());

    // Validate query parameters
    const result = GetTradesQuerySchema.safeParse(queryParams);
    if (!result.success) {
      return NextResponse.json(
        { trades: [], error: `Invalid parameters: ${result.error.message}` },
        { status: 400 }
      );
    }

    const trades = await getRecentTrades(result.data.limit);

    return NextResponse.json(
      { trades },
      {
        headers: {
          'Cache-Control': 'private, max-age=5', // Short cache for trade data
        },
      }
    );
  } catch (error) {
    console.error('Error fetching trades:', error);
    return NextResponse.json({ trades: [], error: 'Database error' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();

    // Validate input
    const result = CreateTradeSchema.safeParse(body);
    if (!result.success) {
      return NextResponse.json(
        { error: `Validation failed: ${result.error.message}` },
        { status: 400 }
      );
    }

    // Transform to match Trade type (convert undefined to null)
    const tradeData: Omit<Trade, 'id' | 'created_at' | 'updated_at'> = {
      market_ticker: result.data.market_ticker,
      side: result.data.side,
      action: result.data.action,
      contracts: result.data.contracts,
      entry_price_cents: result.data.entry_price_cents,
      fill_price_cents: result.data.fill_price_cents ?? null,
      exit_price_cents: result.data.exit_price_cents ?? null,
      pnl_cents: result.data.pnl_cents ?? null,
      order_id: result.data.order_id ?? null,
      exit_order_id: result.data.exit_order_id ?? null,
      status: result.data.status ?? 'pending',
      reasoning: result.data.reasoning ?? null,
      exit_reason: result.data.exit_reason ?? null,
      strategy: result.data.strategy ?? 'mean_reversion',
      session_date: result.data.session_date ?? null,
      metadata: result.data.metadata ?? null,
    };

    const trade = await createTrade(tradeData);
    return NextResponse.json({ trade }, { status: 201 });
  } catch (error) {
    console.error('Error creating trade:', error);
    return NextResponse.json({ error: 'Failed to create trade' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json();

    // Validate input
    const result = UpdateTradeSchema.safeParse(body);
    if (!result.success) {
      return NextResponse.json(
        { error: `Validation failed: ${result.error.message}` },
        { status: 400 }
      );
    }

    const { id, ...rawUpdates } = result.data;

    // Transform to match Trade type (convert undefined to null where appropriate)
    const updates: Partial<Trade> = {};
    if (rawUpdates.fill_price_cents !== undefined) updates.fill_price_cents = rawUpdates.fill_price_cents;
    if (rawUpdates.exit_price_cents !== undefined) updates.exit_price_cents = rawUpdates.exit_price_cents;
    if (rawUpdates.pnl_cents !== undefined) updates.pnl_cents = rawUpdates.pnl_cents;
    if (rawUpdates.exit_order_id !== undefined) updates.exit_order_id = rawUpdates.exit_order_id;
    if (rawUpdates.status !== undefined) updates.status = rawUpdates.status;
    if (rawUpdates.exit_reason !== undefined) updates.exit_reason = rawUpdates.exit_reason;
    if (rawUpdates.metadata !== undefined) updates.metadata = rawUpdates.metadata;

    const trade = await updateTrade(id, updates);

    if (!trade) {
      return NextResponse.json({ error: 'Trade not found' }, { status: 404 });
    }

    return NextResponse.json({ trade });
  } catch (error) {
    console.error('Error updating trade:', error);
    return NextResponse.json({ error: 'Failed to update trade' }, { status: 500 });
  }
}
