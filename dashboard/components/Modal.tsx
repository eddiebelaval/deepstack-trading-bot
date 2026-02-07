'use client';

import { useEffect, useCallback } from 'react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const SIZE_CLASSES = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
} as const;

export default function Modal({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  size = 'md'
}: ModalProps): JSX.Element | null {
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'unset';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-85 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className={`bg-terminal-black border border-terminal-green ${SIZE_CLASSES[size]} w-full max-h-[85vh] flex flex-col`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="border-b border-terminal-green p-4 flex-shrink-0">
          <div className="flex justify-between items-start">
            <div>
              {subtitle && (
                <div className="text-xs text-terminal-dim mb-1">{subtitle}</div>
              )}
              <div className="text-lg font-bold terminal-glow tracking-wide">
                {title}
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-terminal-dim hover:text-terminal-green transition-colors text-xl leading-none"
            >
              [x]
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto flex-1">
          {children}
        </div>

        {/* Footer */}
        <div className="border-t border-terminal-green p-3 flex-shrink-0">
          <div className="text-xs text-terminal-dim text-center">
            [ESC] or click outside to close
          </div>
        </div>
      </div>
    </div>
  );
}
