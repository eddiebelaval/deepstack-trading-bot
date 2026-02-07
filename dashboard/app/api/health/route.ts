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
      error?: string;
    };
  };
}

export async function GET(): Promise<NextResponse<HealthStatus>> {
  const startTime = Date.now();
  const timestamp = new Date().toISOString();

  // Database health check
  let dbStatus: 'up' | 'down' = 'down';
  let dbLatency = 0;
  let dbError: string | undefined;

  try {
    const dbStart = Date.now();
    const ok = await healthCheck();
    dbLatency = Date.now() - dbStart;
    dbStatus = ok ? 'up' : 'down';
  } catch (error) {
    dbError = error instanceof Error ? error.message : 'Unknown database error';
    dbLatency = Date.now() - startTime;
  }

  // Determine overall status
  let overallStatus: 'healthy' | 'degraded' | 'unhealthy' = 'healthy';
  if (dbStatus === 'down') {
    overallStatus = 'unhealthy';
  } else if (dbLatency > 1000) {
    // Slow database response
    overallStatus = 'degraded';
  }

  const healthResponse: HealthStatus = {
    status: overallStatus,
    timestamp,
    version: process.env.npm_package_version || '0.1.0',
    checks: {
      database: {
        status: dbStatus,
        latencyMs: dbLatency,
        ...(dbError && { error: dbError }),
      },
    },
  };

  // Return appropriate HTTP status code
  const httpStatus = overallStatus === 'healthy' ? 200 : overallStatus === 'degraded' ? 200 : 503;

  return NextResponse.json(healthResponse, {
    status: httpStatus,
    headers: {
      'Cache-Control': 'no-store, max-age=0',
    },
  });
}
