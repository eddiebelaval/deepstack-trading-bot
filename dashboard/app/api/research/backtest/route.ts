import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { url } = await request.json();

    if (!url || !url.includes('tradingview.com/script/')) {
      return NextResponse.json(
        { error: 'Invalid TradingView URL. Must contain tradingview.com/script/' },
        { status: 400 }
      );
    }

    const apiUrl = process.env.DS_TV_API_URL;
    if (!apiUrl) {
      return NextResponse.json({ error: 'DS_TV_API_URL not configured' }, { status: 503 });
    }
    const res = await fetch(`${apiUrl}/backtest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { error: 'Backtest service unavailable. The pipeline may not be running.' },
      { status: 503 }
    );
  }
}
