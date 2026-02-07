'use client';

import { useEffect, useState } from 'react';

export interface ToastMessage {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
  timestamp: Date;
}

interface ToastProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
}

const TOAST_CONFIG = {
  success: { border: 'border-terminal-green', icon: '[OK]', iconColor: 'text-terminal-green-bright' },
  warning: { border: 'border-terminal-amber', icon: '[!!]', iconColor: 'text-terminal-amber' },
  error: { border: 'border-terminal-red', icon: '[XX]', iconColor: 'text-terminal-red-bright' },
  info: { border: 'border-terminal-cyan', icon: '[i]', iconColor: 'text-terminal-cyan' },
} as const;

function Toast({ toast, onDismiss }: ToastProps): JSX.Element {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), 4000);
    return () => clearTimeout(timer);
  }, [toast.id, onDismiss]);

  const config = TOAST_CONFIG[toast.type];
  const timeStr = toast.timestamp.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  return (
    <div
      className={`bg-terminal-bg-panel border ${config.border} px-4 py-2 flex items-center gap-3 text-sm font-mono animate-fade-in rounded-lg`}
      style={{ animation: 'fade-in 0.3s ease-out' }}
    >
      <span className={`${config.iconColor} font-bold`}>{config.icon}</span>
      <span className="text-terminal-cyan-dim">{timeStr}</span>
      <span className="text-terminal-green flex-1">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="text-terminal-dim hover:text-terminal-green transition-colors"
      >
        [x]
      </button>
    </div>
  );
}

interface ToastContainerProps {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
}

export default function ToastContainer({ toasts, onDismiss }: ToastContainerProps): JSX.Element | null {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-md">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

export interface UseToastsReturn {
  toasts: ToastMessage[];
  addToast: (type: ToastMessage['type'], message: string) => void;
  dismissToast: (id: string) => void;
}

export function useToasts(): UseToastsReturn {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  function addToast(type: ToastMessage['type'], message: string): void {
    const newToast: ToastMessage = {
      id: `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`,
      type,
      message,
      timestamp: new Date(),
    };
    setToasts((prev) => [...prev, newToast]);
  }

  function dismissToast(id: string): void {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  return { toasts, addToast, dismissToast };
}
