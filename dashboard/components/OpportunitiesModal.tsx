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
        setOpportunities((data.opportunities || []).map((opp: Record<string, unknown>) => ({
          ...opp,
          current_price: Number(opp.current_price_cents) || 0,
          target_price: Number(opp.target_price_cents) || 0,
          expected_profit_pct: Number(opp.expected_profit_pct) || 0,
          confidence: Number(opp.confidence) || 0,
          detected_at: opp.created_at,
        })));
      } else {
        setOpportunities([]);
      }
    } catch {
      setOpportunities([]);
    }
    setLoading(false);
  };

  const filteredOpps = filter === 'all'
    ? opportunities
    : opportunities.filter(opp => opp.status === filter);

  function getStatusColor(status: string): string {
    switch (status) {
      case 'active': return 'text-terminal-green';
      case 'taken': return 'text-terminal-amber';
      default: return 'text-terminal-dim';
    }
  }

  function getConfidenceColor(confidence: number): string {
    if (confidence >= 0.8) return 'text-terminal-green-bright';
    if (confidence >= 0.6) return 'text-terminal-amber';
    return 'text-terminal-red';
  }

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
                    +{(Number(opp.expected_profit_pct) || 0).toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="text-terminal-dim text-xs">CONFIDENCE</div>
                  <div className={`tabular-nums ${getConfidenceColor(Number(opp.confidence) || 0)}`}>
                    {((Number(opp.confidence) || 0) * 100).toFixed(0)}%
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

