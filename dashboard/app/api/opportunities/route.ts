import { NextResponse } from 'next/server';
import { getOpportunities, createOpportunity, updateOpportunityStatus } from '@/lib/db-postgres';
import {
  GetOpportunitiesQuerySchema,
  CreateOpportunitySchema,
  UpdateOpportunitySchema,
} from '@/lib/validation';
import { Opportunity } from '@/lib/types';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const queryParams = Object.fromEntries(searchParams.entries());

    // Validate query parameters
    const result = GetOpportunitiesQuerySchema.safeParse(queryParams);
    if (!result.success) {
      return NextResponse.json(
        { opportunities: [], error: `Invalid parameters: ${result.error.message}` },
        { status: 400 }
      );
    }

    const opportunities = await getOpportunities(result.data.status, result.data.limit);

    return NextResponse.json(
      { opportunities },
      {
        headers: {
          'Cache-Control': 'private, max-age=10', // Short cache for opportunity data
        },
      }
    );
  } catch (error) {
    console.error('Error fetching opportunities:', error);
    return NextResponse.json({ opportunities: [], error: 'Database error' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();

    // Validate input
    const result = CreateOpportunitySchema.safeParse(body);
    if (!result.success) {
      return NextResponse.json(
        { error: `Validation failed: ${result.error.message}` },
        { status: 400 }
      );
    }

    // Transform to match Opportunity type
    const oppData: Omit<Opportunity, 'id' | 'created_at' | 'taken_at' | 'expired_at' | 'trade_id'> = {
      market_ticker: result.data.market_ticker,
      strategy: result.data.strategy,
      side: result.data.side,
      current_price_cents: result.data.current_price_cents,
      target_price_cents: result.data.target_price_cents,
      expected_profit_pct: result.data.expected_profit_pct,
      confidence: result.data.confidence,
      status: result.data.status ?? 'active',
      reasoning: result.data.reasoning ?? null,
    };

    const opportunity = await createOpportunity(oppData);
    return NextResponse.json({ opportunity }, { status: 201 });
  } catch (error) {
    console.error('Error creating opportunity:', error);
    return NextResponse.json({ error: 'Failed to create opportunity' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json();

    // Validate input
    const result = UpdateOpportunitySchema.safeParse(body);
    if (!result.success) {
      return NextResponse.json(
        { error: `Validation failed: ${result.error.message}` },
        { status: 400 }
      );
    }

    const { id, status, trade_id } = result.data;
    const opportunity = await updateOpportunityStatus(id, status, trade_id);

    if (!opportunity) {
      return NextResponse.json({ error: 'Opportunity not found' }, { status: 404 });
    }

    return NextResponse.json({ opportunity });
  } catch (error) {
    console.error('Error updating opportunity:', error);
    return NextResponse.json({ error: 'Failed to update opportunity' }, { status: 500 });
  }
}
