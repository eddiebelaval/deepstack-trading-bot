import { useEffect, useRef } from 'react';

export interface ShortcutHandlers {
  onRefresh?: () => void;
  onToggleSound?: () => void;
  onHelp?: () => void;
}

function isTypingInInput(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
}

function hasModifierKey(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.metaKey;
}

export function useKeyboardShortcuts(handlers: ShortcutHandlers): void {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent): void {
      if (isTypingInInput(event.target)) return;

      const key = event.key.toLowerCase();
      const h = handlersRef.current;

      if ((key === 'r' || key === 's') && hasModifierKey(event)) return;

      switch (key) {
        case 'r':
          event.preventDefault();
          h.onRefresh?.();
          break;
        case 's':
          event.preventDefault();
          h.onToggleSound?.();
          break;
        case '?':
        case 'h':
          event.preventDefault();
          h.onHelp?.();
          break;
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);
}

export const KEYBOARD_SHORTCUTS = [
  { key: 'R', description: 'Refresh data' },
  { key: 'S', description: 'Toggle sound' },
  { key: '?', description: 'Show shortcuts' },
] as const;
