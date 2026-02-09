import { NextResponse } from 'next/server';
import { getOrders } from '@/lib/db-postgres';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const status = searchParams.get('status') || undefined;
    const orders = await getOrders(status);
    return NextResponse.json(
      { orders },
      { headers: { 'Cache-Control': 'private, max-age=5' } }
    );
  } catch (error) {
    console.error('Error fetching orders:', error);
    return NextResponse.json({ orders: [], error: 'Database error' }, { status: 500 });
  }
}
