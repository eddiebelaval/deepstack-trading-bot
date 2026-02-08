import { NextResponse } from 'next/server';
import { getBotConfig, updateBotConfig } from '@/lib/db-postgres';
import { UpdateBotConfigSchema, validateRequest } from '@/lib/validation';

export async function GET() {
  try {
    const config = await getBotConfig();
    if (!config) {
      return NextResponse.json({ error: 'Bot config not found' }, { status: 404 });
    }
    return NextResponse.json({ config });
  } catch (error) {
    console.error('Failed to fetch bot config:', error);
    return NextResponse.json({ error: 'Failed to fetch config' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json();
    const validation = validateRequest(UpdateBotConfigSchema, body);

    if (!validation.success) {
      return NextResponse.json({ error: validation.error }, { status: 400 });
    }

    const updated = await updateBotConfig(validation.data);
    if (!updated) {
      return NextResponse.json({ error: 'No fields to update' }, { status: 400 });
    }

    return NextResponse.json({ config: updated });
  } catch (error) {
    console.error('Failed to update bot config:', error);
    return NextResponse.json({ error: 'Failed to update config' }, { status: 500 });
  }
}
