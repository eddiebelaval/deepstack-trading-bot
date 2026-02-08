import { useCallback, useRef, useState } from 'react';

type AudioContextType = typeof AudioContext;

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const AudioContextClass = window.AudioContext || (window as { webkitAudioContext?: AudioContextType }).webkitAudioContext;
  if (!AudioContextClass) return null;
  return new AudioContextClass();
}

function playTone(
  frequency: number,
  duration: number,
  volume: number,
  type: OscillatorType = 'square',
): void {
  const audioContext = getAudioContext();
  if (!audioContext) return;

  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();

  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);

  oscillator.frequency.value = frequency;
  oscillator.type = type;
  gainNode.gain.value = volume;

  // Fade out to avoid click artifacts
  gainNode.gain.setValueAtTime(volume, audioContext.currentTime);
  gainNode.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + duration);

  oscillator.start();
  oscillator.stop(audioContext.currentTime + duration);
}

export interface UseSoundEffectsReturn {
  enabled: boolean;
  toggle: () => void;
  playTrade: () => void;
  playBuy: () => void;
  playSell: () => void;
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
    playTone(800, 0.05, 0.08);
    setTimeout(() => playTone(1000, 0.05, 0.08), 80);
  }, []);

  // BUY: ascending two-tone chime (low to high) — feels like "going in"
  const playBuy = useCallback((): void => {
    if (!enabledRef.current) return;
    playTone(520, 0.12, 0.10, 'sine');
    setTimeout(() => playTone(780, 0.15, 0.10, 'sine'), 130);
  }, []);

  // SELL: descending two-tone chime (high to low) — feels like "cashing out"
  const playSell = useCallback((): void => {
    if (!enabledRef.current) return;
    playTone(780, 0.12, 0.10, 'sine');
    setTimeout(() => playTone(520, 0.15, 0.10, 'sine'), 130);
  }, []);

  const playError = useCallback((): void => {
    if (!enabledRef.current) return;
    playTone(200, 0.2, 0.1);
  }, []);

  const playSuccess = useCallback((): void => {
    if (!enabledRef.current) return;
    playTone(600, 0.08, 0.06);
    setTimeout(() => playTone(800, 0.08, 0.06), 100);
    setTimeout(() => playTone(1000, 0.08, 0.06), 200);
  }, []);

  const playNotification = useCallback((): void => {
    if (!enabledRef.current) return;
    playTone(600, 0.1, 0.05);
  }, []);

  const toggle = useCallback((): void => {
    setEnabled((prev) => !prev);
  }, []);

  return { enabled, toggle, playTrade, playBuy, playSell, playError, playSuccess, playNotification };
}
