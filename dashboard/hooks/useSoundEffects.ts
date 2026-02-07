import { useCallback, useRef, useState } from 'react';

type AudioContextType = typeof AudioContext;

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const AudioContextClass = window.AudioContext || (window as { webkitAudioContext?: AudioContextType }).webkitAudioContext;
  if (!AudioContextClass) return null;
  return new AudioContextClass();
}

function playBeep(frequency: number, duration: number, volume: number): void {
  const audioContext = getAudioContext();
  if (!audioContext) return;

  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();

  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);

  oscillator.frequency.value = frequency;
  oscillator.type = 'square';
  gainNode.gain.value = volume;

  oscillator.start();
  oscillator.stop(audioContext.currentTime + duration);
}

export interface UseSoundEffectsReturn {
  enabled: boolean;
  toggle: () => void;
  playTrade: () => void;
  playError: () => void;
  playSuccess: () => void;
  playNotification: () => void;
}

export function useSoundEffects(): UseSoundEffectsReturn {
  const [enabled, setEnabled] = useState(false);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const playTrade = useCallback((): void => {
    if (!enabledRef.current) return;
    playBeep(800, 0.05, 0.08);
    setTimeout(() => playBeep(1000, 0.05, 0.08), 80);
  }, []);

  const playError = useCallback((): void => {
    if (!enabledRef.current) return;
    playBeep(200, 0.2, 0.1);
  }, []);

  const playSuccess = useCallback((): void => {
    if (!enabledRef.current) return;
    playBeep(600, 0.08, 0.06);
    setTimeout(() => playBeep(800, 0.08, 0.06), 100);
    setTimeout(() => playBeep(1000, 0.08, 0.06), 200);
  }, []);

  const playNotification = useCallback((): void => {
    if (!enabledRef.current) return;
    playBeep(600, 0.1, 0.05);
  }, []);

  const toggle = useCallback((): void => {
    setEnabled((prev) => !prev);
  }, []);

  return { enabled, toggle, playTrade, playError, playSuccess, playNotification };
}
