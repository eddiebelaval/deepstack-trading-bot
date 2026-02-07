import { NextResponse } from 'next/server';
import { healthCheck } from '@/lib/postgres';

interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: string;
  version: string;
  checks: {
    database: {
      status: 'up' | 'down';
      latencyMs: number;
    };
  };
}

export async function GET(): Promise<NextResponse<HealthStatus>> {
  const startTime = Date.now();
  const timestamp = new Date().toISOString();

  let dbStatus: 'up' | 'down' = 'down';
  let dbLatency = 0;

  try {
    const dbStart = Date.now();
    const ok = await healthCheck();
    dbLatency = Date.now() - dbStart;
    dbStatus = ok ? 'up' : 'down';
  } catch {
    // Log internally but do not expose error details to unauthenticated endpoint
    dbLatency = Date.now() - startTime;
  }

  let overallStatus: 'healthy' | 'degraded' | 'unhealthy' = 'healthy';
  if (dbStatus === 'down') {
    overallStatus = 'unhealthy';
  } else if (dbLatency > 1000) {
    overallStatus = 'degraded';
  }

  const healthResponse: HealthStatus = {
    status: overallStatus,
    timestamp,
    version: '0.1.0',
    checks: {
      database: {
        status: dbStatus,
        latencyMs: dbLatency,
      },
    },
  };

  const httpStatus = overallStatus === 'unhealthy' ? 503 : 200;

  return NextResponse.json(healthResponse, {
    status: httpStatus,
    headers: {
      'Cache-Control': 'no-store, max-age=0',
    },
  });
}
