'use client';

import { useState, useEffect, useCallback } from 'react';
import Modal from './Modal';
import { getStrategyMeta, type ConfigField, type RiskProfile, type StrategyCategory } from '@/lib/strategy-meta';
import type { StrategyConfig } from '@/lib/strategy-defaults';

interface StrategyInfoModalProps {
  strategyName: string | null;
  onClose: () => void;
}

type Tab = 'about' | 'config';
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const RISK_COLORS: Record<RiskProfile, { text: string; bg: string; border: string }> = {
  conservative: { text: 'text-terminal-green', bg: 'bg-terminal-green/15', border: 'border-terminal-green/40' },
  moderate: { text: 'text-terminal-amber', bg: 'bg-terminal-amber/15', border: 'border-terminal-amber/40' },
  aggressive: { text: 'text-terminal-red', bg: 'bg-terminal-red/15', border: 'border-terminal-red/40' },
};

const CATEGORY_COLORS: Record<StrategyCategory, string> = {
  original: 'text-terminal-green bg-terminal-green/10 border-terminal-green/30',
  prediction_market: 'text-terminal-cyan bg-terminal-cyan/10 border-terminal-cyan/30',
  crypto: 'text-terminal-amber bg-terminal-amber/10 border-terminal-amber/30',
};

export default function StrategyInfoModal({ strategyName, onClose }: StrategyInfoModalProps) {
  const [tab, setTab] = useState<Tab>('about');
  const [config, setConfig] = useState<StrategyConfig>({});
  const [defaults, setDefaults] = useState<StrategyConfig>({});
  const [overrides, setOverrides] = useState<StrategyConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const meta = strategyName ? getStrategyMeta(strategyName) : null;

  const loadConfig = useCallback(async (name: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/strategies/${name}/config`);
      if (res.ok) {
        const data = await res.json();
        setDefaults(data.defaults);
        setOverrides(data.overrides);
        setConfig(data.merged);
      }
    } catch (err) {
      console.error('Failed to load config:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (strategyName) {
      setTab('about');
      setSaveStatus('idle');
      setShowResetConfirm(false);
      loadConfig(strategyName);
    }
  }, [strategyName, loadConfig]);

  async function handleSave() {
    if (!strategyName) return;
    setSaveStatus('saving');
    try {
      // Build overrides: only include values that differ from defaults
      const newOverrides: StrategyConfig = {};
      for (const [key, value] of Object.entries(config)) {
        if (defaults[key] !== value) {
          newOverrides[key] = value;
        }
      }

      const res = await fetch(`/api/strategies/${strategyName}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides: Object.keys(newOverrides).length > 0 ? newOverrides : null }),
      });

      if (res.ok) {
        const data = await res.json();
        setOverrides(data.overrides);
        setConfig(data.merged);
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      } else {
        const err = await res.json();
        console.error('Save failed:', err);
        setSaveStatus('error');
        setTimeout(() => setSaveStatus('idle'), 3000);
      }
    } catch {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 3000);
    }
  }

  async function handleReset() {
    if (!strategyName) return;
    setSaveStatus('saving');
    try {
      const res = await fetch(`/api/strategies/${strategyName}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides: null }),
      });
      if (res.ok) {
        const data = await res.json();
        setOverrides(null);
        setConfig(data.merged);
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      }
    } catch {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 3000);
    }
  }

  function updateField(key: string, value: number | boolean | string) {
    setConfig(prev => ({ ...prev, [key]: value }));
    setSaveStatus('idle');
  }

  function isModified(key: string): boolean {
    return overrides !== null && key in overrides;
  }

  if (!strategyName || !meta) return null;

  const riskStyle = RISK_COLORS[meta.riskProfile];
  const catStyle = CATEGORY_COLORS[meta.category];

  return (
    <Modal
      isOpen={!!strategyName}
      onClose={onClose}
      title={meta.displayName}
      subtitle={meta.edgeType}
      size="lg"
    >
      {/* Tab Bar */}
      <div className="flex gap-1 mb-5 border-b border-terminal-green/20 -mt-1">
        {(['about', 'config'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-xs font-bold tracking-[0.15em] uppercase transition-all border-b-2 -mb-px ${
              tab === t
                ? 'border-terminal-green text-terminal-green'
                : 'border-transparent text-terminal-dim hover:text-terminal-green/60'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ABOUT Tab */}
      {tab === 'about' && (
        <div className="space-y-5">
          {/* Badges */}
          <div className="flex flex-wrap gap-2">
            <span className={`text-[10px] font-bold px-2 py-1 rounded border ${catStyle}`}>
              {meta.category.replace('_', ' ').toUpperCase()}
            </span>
            <span className={`text-[10px] font-bold px-2 py-1 rounded border ${riskStyle.text} ${riskStyle.bg} ${riskStyle.border}`}>
              {meta.riskProfile.toUpperCase()} RISK
            </span>
            <span className="text-[10px] font-bold px-2 py-1 rounded border text-terminal-cyan bg-terminal-cyan/10 border-terminal-cyan/30">
              {(meta.expectedWinRate * 100).toFixed(0)}% WIN RATE
            </span>
          </div>

          {/* How it Works */}
          <div>
            <div className="text-[10px] text-terminal-dim tracking-[0.15em] uppercase mb-2">How It Works</div>
            <p className="text-sm text-terminal-green/80 leading-relaxed">
              {meta.howItWorks}
            </p>
          </div>

          {/* Edge Type */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-[10px] text-terminal-dim tracking-[0.15em] uppercase mb-1">Edge Type</div>
              <div className="text-sm font-bold text-terminal-cyan">{meta.edgeType}</div>
            </div>
            <div>
              <div className="text-[10px] text-terminal-dim tracking-[0.15em] uppercase mb-1">Config Fields</div>
              <div className="text-sm font-bold text-terminal-amber">{meta.configSchema.length} params</div>
            </div>
          </div>

          {/* One-liner */}
          <div className="p-3 rounded border border-terminal-green/20 bg-terminal-green/[0.03]">
            <div className="text-[10px] text-terminal-dim tracking-[0.15em] uppercase mb-1">Summary</div>
            <p className="text-xs text-terminal-green/70">{meta.description}</p>
          </div>
        </div>
      )}

      {/* CONFIG Tab */}
      {tab === 'config' && (
        <div className="space-y-4">
          {loading ? (
            <div className="text-center py-8 text-terminal-dim text-sm animate-pulse">Loading config...</div>
          ) : (
            <>
              {/* Config Fields */}
              <div className="space-y-3">
                {meta.configSchema.map((field) => (
                  <ConfigFieldInput
                    key={field.key}
                    field={field}
                    value={config[field.key]}
                    defaultValue={defaults[field.key]}
                    modified={isModified(field.key)}
                    onChange={(val) => updateField(field.key, val)}
                  />
                ))}
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-3 border-t border-terminal-green/20">
                <button
                  onClick={handleSave}
                  disabled={saveStatus === 'saving'}
                  className={`flex-1 py-2.5 text-xs font-bold border rounded transition-all ${
                    saveStatus === 'saved'
                      ? 'border-terminal-green bg-terminal-green/20 text-terminal-green'
                      : saveStatus === 'error'
                        ? 'border-terminal-red bg-terminal-red/20 text-terminal-red'
                        : 'border-terminal-green text-terminal-green hover:bg-terminal-green/15'
                  }`}
                >
                  {saveStatus === 'saving' ? 'SAVING...' :
                   saveStatus === 'saved' ? 'SAVED' :
                   saveStatus === 'error' ? 'FAILED' : 'SAVE CONFIG'}
                </button>
                {!showResetConfirm ? (
                  <button
                    onClick={() => setShowResetConfirm(true)}
                    disabled={saveStatus === 'saving' || !overrides}
                    className="px-4 py-2.5 text-xs font-bold border border-terminal-dim/30 text-terminal-dim hover:border-terminal-amber/40 hover:text-terminal-amber rounded transition-all disabled:opacity-30"
                  >
                    RESET ALL
                  </button>
                ) : (
                  <div className="flex gap-1">
                    <button
                      onClick={() => { handleReset(); setShowResetConfirm(false); }}
                      className="px-3 py-2.5 text-xs font-bold border border-terminal-red bg-terminal-red/15 text-terminal-red rounded transition-all hover:bg-terminal-red/25"
                    >
                      CONFIRM
                    </button>
                    <button
                      onClick={() => setShowResetConfirm(false)}
                      className="px-3 py-2.5 text-xs font-bold border border-terminal-dim/30 text-terminal-dim rounded transition-all"
                    >
                      CANCEL
                    </button>
                  </div>
                )}
              </div>

              {overrides && Object.keys(overrides).length > 0 && (
                <div className="text-[9px] text-terminal-amber/60 text-center">
                  {Object.keys(overrides).length} field{Object.keys(overrides).length !== 1 ? 's' : ''} customized -- modified fields show defaults below
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Modal>
  );
}

/** Individual config field renderer */
function ConfigFieldInput({
  field,
  value,
  defaultValue,
  modified,
  onChange,
}: {
  field: ConfigField;
  value: number | boolean | string | undefined;
  defaultValue: number | boolean | string | undefined;
  modified: boolean;
  onChange: (val: number | boolean | string) => void;
}) {
  const isChanged = value !== defaultValue;
  const defaultHint = defaultValue !== undefined && isChanged;

  if (field.type === 'boolean') {
    const checked = typeof value === 'boolean' ? value : !!value;
    const defaultChecked = typeof defaultValue === 'boolean' ? defaultValue : !!defaultValue;
    return (
      <div className="py-1">
        <div className="flex items-center justify-between">
          <label className="text-xs text-terminal-green/80 flex items-center gap-2">
            {field.label}
            {modified && <span className="w-1.5 h-1.5 rounded-full bg-terminal-amber" />}
          </label>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onChange(!checked)}
              className={`w-9 h-5 rounded-full relative transition-all duration-300 border flex-shrink-0 ${
                checked
                  ? 'bg-terminal-green/20 border-terminal-green/50'
                  : 'bg-[#1a1a2e] border-[#3a3a55]'
              }`}
            >
              <div className={`absolute top-[3px] w-3.5 h-3.5 rounded-full transition-all duration-300 ${
                checked
                  ? 'right-[3px] bg-terminal-green shadow-[0_0_6px_currentColor]'
                  : 'left-[3px] bg-[#5a5a75]'
              }`} />
            </button>
          </div>
        </div>
        {defaultHint && (
          <button
            onClick={() => onChange(defaultChecked)}
            className="text-[9px] text-terminal-dim/50 hover:text-terminal-amber mt-0.5 ml-0 transition-colors"
          >
            default: {defaultChecked ? 'ON' : 'OFF'} -- click to restore
          </button>
        )}
      </div>
    );
  }

  if (field.type === 'select' && field.options) {
    return (
      <div className="py-1">
        <div className="flex items-center justify-between">
          <label className="text-xs text-terminal-green/80 flex items-center gap-2">
            {field.label}
            {modified && <span className="w-1.5 h-1.5 rounded-full bg-terminal-amber" />}
          </label>
          <select
            value={String(value ?? '')}
            onChange={(e) => onChange(isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value))}
            className="bg-terminal-bg border border-terminal-green/30 text-terminal-green text-xs rounded px-2 py-1.5 focus:border-terminal-green/60 outline-none"
          >
            {field.options.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        {defaultHint && (
          <button
            onClick={() => onChange(defaultValue as string | number)}
            className="text-[9px] text-terminal-dim/50 hover:text-terminal-amber mt-0.5 transition-colors"
          >
            default: {defaultValue} -- click to restore
          </button>
        )}
      </div>
    );
  }

  // Number input
  const numValue = typeof value === 'number' ? value : 0;
  return (
    <div className="py-1">
      <div className="flex items-center justify-between gap-3">
        <label className="text-xs text-terminal-green/80 flex items-center gap-2 flex-shrink-0">
          {field.label}
          {modified && <span className="w-1.5 h-1.5 rounded-full bg-terminal-amber" />}
        </label>
        <div className="flex items-center gap-1.5">
          <input
            type="number"
            value={numValue}
            min={field.min}
            max={field.max}
            step={field.step}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-20 bg-terminal-bg border border-terminal-green/30 text-terminal-green text-xs font-mono rounded px-2 py-1.5 text-right focus:border-terminal-green/60 outline-none tabular-nums"
          />
          {field.suffix && (
            <span className="text-[10px] text-terminal-dim w-6">{field.suffix}</span>
          )}
        </div>
      </div>
      {defaultHint && (
        <button
          onClick={() => onChange(defaultValue as number)}
          className="text-[9px] text-terminal-dim/50 hover:text-terminal-amber mt-0.5 transition-colors"
        >
          default: {defaultValue}{field.suffix ? ` ${field.suffix}` : ''} -- click to restore
        </button>
      )}
    </div>
  );
}
