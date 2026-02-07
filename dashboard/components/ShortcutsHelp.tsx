'use client';

import { KEYBOARD_SHORTCUTS } from '@/hooks/useKeyboardShortcuts';

interface ShortcutsHelpProps {
  isOpen: boolean;
  onClose: () => void;
  soundEnabled: boolean;
}

export default function ShortcutsHelp({ isOpen, onClose, soundEnabled }: ShortcutsHelpProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-terminal-bg/90 backdrop-blur-sm z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="bg-terminal-bg-panel border border-terminal-green/50 p-6 max-w-sm rounded-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-terminal-green/30 pb-2 mb-4">
          <div className="text-xs text-terminal-dim mb-1">SYSTEM</div>
          <div className="text-lg font-bold terminal-glow tracking-wide">
            KEYBOARD SHORTCUTS
          </div>
        </div>

        <div className="space-y-2 font-mono text-sm">
          {KEYBOARD_SHORTCUTS.map((shortcut) => (
            <div key={shortcut.key} className="flex justify-between gap-8">
              <span className="text-terminal-cyan">[{shortcut.key}]</span>
              <span className="text-terminal-green">{shortcut.description}</span>
            </div>
          ))}
        </div>

        <div className="mt-4 pt-4 border-t border-terminal-green/30">
          <div className="flex justify-between text-xs">
            <span className="text-terminal-dim">SOUND:</span>
            <span className={soundEnabled ? 'text-terminal-green' : 'text-terminal-red'}>
              {soundEnabled ? 'ON' : 'OFF'}
            </span>
          </div>
        </div>

        <div className="mt-4 text-center">
          <button
            onClick={onClose}
            className="text-terminal-dim hover:text-terminal-green text-xs transition-colors"
          >
            [ESC or CLICK to close]
          </button>
        </div>
      </div>
    </div>
  );
}
