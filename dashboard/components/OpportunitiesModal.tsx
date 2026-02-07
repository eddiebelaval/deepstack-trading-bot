'use client';

import { useEffect, useState } from 'react';
import Modal from './Modal';

interface Opportunity {
  id: string;
  market: string;
  strategy: string;
  side: 'YES' | 'NO';
  current_price: number;
  target_price: number;
  expected_profit_pct: number;
  confidence: number;
  detected_at: string;
  status: 'active' | 'taken' | 'expired';
  reasoning: string;
}

interface OpportunitiesModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function OpportunitiesModal({ isOpen, onClose }: OpportunitiesModalProps): JSX.Element {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'active' | 'taken'>('all');

  useEffect(() => {
    if (isOpen) {
      fetchOpportunities();
    }
  }, [isOpen]);

  const fetchOpportunities = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/opportunities');
      if (response.ok) {
        const data = await response.json();
        // Use real data if available, otherwise fall back to mock
        if (data.opportunities && data.opportunities.length > 0) {
          setOpportunities(data.opportunities.map((opp: Record<string, unknown>) => ({
            ...opp,
            // Map DB field names to component field names
            current_price: opp.current_price_cents,
            target_price: opp.target_price_cents,
            detected_at: opp.created_at,
          })));
        } else {
          setOpportunities(getMockOpportunities());
        }
      } else {
        setOpportunities(getMockOpportunities());
      }
    } catch {
      setOpportunities(getMockOpportunities());
    }
    setLoading(false);
  };

  const filteredOpps = opportunities.filter(opp => {
    if (filter === 'all') return true;
    return opp.status === filter;
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-terminal-green';
      case 'taken': return 'text-terminal-amber';
      case 'expired': return 'text-terminal-dim';
      default: return 'text-terminal-dim';
    }
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return 'text-terminal-green-bright';
    if (confidence >= 0.6) return 'text-terminal-amber';
    return 'text-terminal-red';
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="OPPORTUNITIES DETECTED"
      subtitle="MARKET SCANNER"
      size="xl"
    >
      {/* Filter Tabs */}
      <div className="flex gap-4 mb-4 border-b border-terminal-green pb-3">
        {(['all', 'active', 'taken'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-sm uppercase tracking-wider transition-colors ${
              filter === f
                ? 'text-terminal-green terminal-glow'
                : 'text-terminal-dim hover:text-terminal-green'
            }`}
          >
            [{f}]
          </button>
        ))}
        <span className="text-terminal-dim text-sm ml-auto">
          {filteredOpps.length} opportunities
        </span>
      </div>

      {loading ? (
        <div className="text-center py-8 text-terminal-dim">
          SCANNING<span className="animate-pulse">...</span>
        </div>
      ) : filteredOpps.length === 0 ? (
        <div className="text-center py-8 text-terminal-dim">
          NO OPPORTUNITIES MATCHING FILTER
        </div>
      ) : (
        <div className="space-y-3">
          {filteredOpps.map((opp) => (
            <div
              key={opp.id}
              className="border border-terminal-green p-3 hover:bg-terminal-green hover:bg-opacity-5 transition-colors"
            >
              {/* Header Row */}
              <div className="flex justify-between items-start mb-2">
                <div>
                  <span className="text-terminal-cyan font-bold">{opp.market}</span>
                  <span className="text-terminal-dim mx-2">/</span>
                  <span className="text-terminal-amber">{opp.strategy}</span>
                </div>
                <span className={`text-xs uppercase ${getStatusColor(opp.status)}`}>
                  [{opp.status}]
                </span>
              </div>

              {/* Details Grid */}
              <div className="grid grid-cols-4 gap-4 text-sm mb-2">
                <div>
                  <div className="text-terminal-dim text-xs">SIDE</div>
                  <div className={opp.side === 'YES' ? 'text-terminal-green' : 'text-terminal-red'}>
                    {opp.side}
                  </div>
                </div>
                <div>
                  <div className="text-terminal-dim text-xs">PRICE</div>
                  <div className="text-terminal-green tabular-nums">
                    {opp.current_price}c → {opp.target_price}c
                  </div>
                </div>
                <div>
                  <div className="text-terminal-dim text-xs">EXP PROFIT</div>
                  <div className="text-terminal-amber-bright tabular-nums">
                    +{opp.expected_profit_pct.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="text-terminal-dim text-xs">CONFIDENCE</div>
                  <div className={`tabular-nums ${getConfidenceColor(opp.confidence)}`}>
                    {(opp.confidence * 100).toFixed(0)}%
                  </div>
                </div>
              </div>

              {/* Reasoning */}
              <div className="text-xs text-terminal-dim border-t border-terminal-green border-opacity-30 pt-2 mt-2">
                <span className="text-terminal-cyan">[REASON]</span> {opp.reasoning}
              </div>

              {/* Timestamp */}
              <div className="text-xs text-terminal-dim mt-1">
                Detected: {new Date(opp.detected_at).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

function getMockOpportunities(): Opportunity[] {
  return [
    {
      id: '1',
      market: 'INXD-26JAN27-5350',
      strategy: 'MOMENTUM',
      side: 'YES',
      current_price: 42,
      target_price: 55,
      expected_profit_pct: 31.0,
      confidence: 0.78,
      detected_at: new Date(Date.now() - 300000).toISOString(),
      status: 'active',
      reasoning: 'Price below fair value based on recent S&P movement. RSI oversold at 28.',
    },
    {
      id: '2',
      market: 'INXD-26JAN27-5375',
      strategy: 'MEAN_REVERSION',
      side: 'NO',
      current_price: 67,
      target_price: 50,
      expected_profit_pct: 34.0,
      confidence: 0.82,
      detected_at: new Date(Date.now() - 600000).toISOString(),
      status: 'active',
      reasoning: 'Overbought condition detected. Historical reversion rate 73% within 2 hours.',
    },
    {
      id: '3',
      market: 'INXD-26JAN27-5325',
      strategy: 'ARBITRAGE',
      side: 'YES',
      current_price: 38,
      target_price: 45,
      expected_profit_pct: 18.4,
      confidence: 0.91,
      detected_at: new Date(Date.now() - 1200000).toISOString(),
      status: 'taken',
      reasoning: 'Cross-platform spread detected: Polymarket 46c vs Kalshi 38c.',
    },
    {
      id: '4',
      market: 'INXD-26JAN27-5400',
      strategy: 'MOMENTUM',
      side: 'YES',
      current_price: 23,
      target_price: 35,
      expected_profit_pct: 52.2,
      confidence: 0.65,
      detected_at: new Date(Date.now() - 1800000).toISOString(),
      status: 'expired',
      reasoning: 'Strong upward momentum but low liquidity. Position size limited.',
    },
  ];
}
