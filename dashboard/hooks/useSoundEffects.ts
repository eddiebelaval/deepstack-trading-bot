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

// Volume presets map to gain multipliers
export type VolumeLevel = 'off' | 'low' | 'medium' | 'high';
const VOLUME_MULTIPLIERS: Record<VolumeLevel, number> = {
  off: 0,
  low: 0.4,
  medium: 0.7,
  high: 1.0,
};

// Sound definitions — each is a sequence of tones
interface ToneStep {
  freq: number;
  dur: number;
  gain: number;
  type: OscillatorType;
  delay: number; // ms offset from start
}

const SOUNDS: Record<string, ToneStep[]> = {
  buy: [
    { freq: 520, dur: 0.12, gain: 0.10, type: 'sine', delay: 0 },
    { freq: 780, dur: 0.15, gain: 0.10, type: 'sine', delay: 130 },
  ],
  sell: [
    { freq: 780, dur: 0.12, gain: 0.10, type: 'sine', delay: 0 },
    { freq: 520, dur: 0.15, gain: 0.10, type: 'sine', delay: 130 },
  ],
  trade: [
    { freq: 800, dur: 0.05, gain: 0.08, type: 'square', delay: 0 },
    { freq: 1000, dur: 0.05, gain: 0.08, type: 'square', delay: 80 },
  ],
  success: [
    { freq: 600, dur: 0.08, gain: 0.06, type: 'square', delay: 0 },
    { freq: 800, dur: 0.08, gain: 0.06, type: 'square', delay: 100 },
    { freq: 1000, dur: 0.08, gain: 0.06, type: 'square', delay: 200 },
  ],
  error: [
    { freq: 200, dur: 0.2, gain: 0.10, type: 'square', delay: 0 },
  ],
  notification: [
    { freq: 600, dur: 0.1, gain: 0.05, type: 'square', delay: 0 },
  ],
};

export type SoundName = keyof typeof SOUNDS;

export interface UseSoundEffectsReturn {
  enabled: boolean;
  volume: VolumeLevel;
  toggle: () => void;
  setVolume: (level: VolumeLevel) => void;
  playTrade: () => void;
  playBuy: () => void;
  playSell: () => void;
  playError: () => void;
  playSuccess: () => void;
  playNotification: () => void;
  preview: (sound: SoundName) => void;
}

export function useSoundEffects(): UseSoundEffectsReturn {
  const [enabled, setEnabled] = useState(false);
  const [volume, setVolumeState] = useState<VolumeLevel>('medium');
  const enabledRef = useRef(enabled);
  const volumeRef = useRef(volume);
  enabledRef.current = enabled;
  volumeRef.current = volume;

  // Core player — applies volume multiplier
  const playSound = useCallback((name: string, force = false): void => {
    if (!force && !enabledRef.current) return;
    const steps = SOUNDS[name];
    if (!steps) return;
    const mult = VOLUME_MULTIPLIERS[volumeRef.current];
    if (mult === 0 && !force) return;
    const effectiveMult = force ? Math.max(mult, VOLUME_MULTIPLIERS.medium) : mult;

    for (const step of steps) {
      if (step.delay === 0) {
        playTone(step.freq, step.dur, step.gain * effectiveMult, step.type);
      } else {
        setTimeout(() => playTone(step.freq, step.dur, step.gain * effectiveMult, step.type), step.delay);
      }
    }
  }, []);

  const playTrade = useCallback(() => playSound('trade'), [playSound]);
  const playBuy = useCallback(() => playSound('buy'), [playSound]);
  const playSell = useCallback(() => playSound('sell'), [playSound]);
  const playError = useCallback(() => playSound('error'), [playSound]);
  const playSuccess = useCallback(() => playSound('success'), [playSound]);
  const playNotification = useCallback(() => playSound('notification'), [playSound]);

  // Preview always plays (ignores enabled state) — for the settings panel
  const preview = useCallback((sound: SoundName) => playSound(sound, true), [playSound]);

  const toggle = useCallback((): void => {
    setEnabled((prev) => !prev);
  }, []);

  const setVolume = useCallback((level: VolumeLevel): void => {
    setVolumeState(level);
    if (level === 'off') {
      setEnabled(false);
    } else if (!enabledRef.current) {
      setEnabled(true);
    }
  }, []);

  return {
    enabled, volume, toggle, setVolume,
    playTrade, playBuy, playSell, playError, playSuccess, playNotification,
    preview,
  };
}
