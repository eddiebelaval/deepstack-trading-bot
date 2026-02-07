import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        terminal: {
          // Base
          black: "#0D0208",

          // Green hierarchy (primary)
          green: "#00FF41",
          "green-dim": "#00AA2B",
          "green-bright": "#39FF14",
          "green-glow": "#00FF88",
          "green-muted": "#005518",

          // Amber/Yellow (secondary - for warnings, medium priority)
          amber: "#FFBF00",
          "amber-bright": "#FFD700",
          "amber-dim": "#CC9900",
          "amber-muted": "#665200",

          // Cyan (tertiary - for info, timestamps)
          cyan: "#00FFFF",
          "cyan-dim": "#00AAAA",

          // Red (errors, losses)
          red: "#FF0000",
          "red-bright": "#FF3333",
          "red-dim": "#AA0000",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      animation: {
        'blink': 'blink 1s step-end infinite',
        'cursor-blink': 'cursor-blink 1s step-end infinite',
        'flicker': 'flicker 0.15s infinite',
        'subtle-flicker': 'subtle-flicker 0.2s infinite',
        'screen-flicker': 'screen-flicker 0.15s infinite',
        'scanline': 'scanline 8s linear infinite',
        'scanlines-move': 'scanlines-move 8s linear infinite',
        'phosphor-pulse': 'phosphor-pulse 2s ease-in-out infinite',
        'live-pulse': 'live-pulse 1.2s ease-in-out infinite',
        'error-pulse': 'error-pulse 1s ease-in-out infinite',
        'amber-pulse': 'amber-pulse 2s ease-in-out infinite',
        'typewriter': 'typewriter 2s steps(40) 1s forwards',
        'fade-in': 'fade-in 0.4s ease-out',
        'scan-sweep': 'scan-sweep 0.5s ease',
        'glow-pulse': 'glow-pulse 2s ease-in-out infinite',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'cursor-blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
        flicker: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.95' },
        },
        'subtle-flicker': {
          '0%': { opacity: '1' },
          '25%': { opacity: '0.98' },
          '50%': { opacity: '1' },
          '75%': { opacity: '0.99' },
          '100%': { opacity: '1' },
        },
        scanline: {
          '0%': {
            transform: 'translateY(-100%)',
            opacity: '0'
          },
          '10%': {
            opacity: '1'
          },
          '90%': {
            opacity: '1'
          },
          '100%': {
            transform: 'translateY(100vh)',
            opacity: '0'
          },
        },
        'phosphor-pulse': {
          '0%, 100%': {
            textShadow: '0 0 3px rgba(0, 255, 65, 1), 0 0 8px rgba(0, 255, 65, 0.9), 0 0 15px rgba(0, 255, 65, 0.7), 0 0 25px rgba(0, 255, 65, 0.5), 0 0 40px rgba(0, 255, 65, 0.3)'
          },
          '50%': {
            textShadow: '0 0 4px rgba(0, 255, 65, 1), 0 0 10px rgba(0, 255, 65, 1), 0 0 20px rgba(0, 255, 65, 0.8), 0 0 30px rgba(0, 255, 65, 0.6), 0 0 50px rgba(0, 255, 65, 0.4)'
          },
        },
        'live-pulse': {
          '0%, 100%': {
            opacity: '1',
            textShadow: '0 0 5px #39FF14, 0 0 10px #39FF14, 0 0 20px #00FF41, 0 0 30px #00FF41, 0 0 40px rgba(0, 255, 65, 0.5)',
            transform: 'scale(1)'
          },
          '50%': {
            opacity: '0.85',
            textShadow: '0 0 8px #39FF14, 0 0 16px #39FF14, 0 0 30px #00FF41, 0 0 50px #00FF41, 0 0 70px rgba(0, 255, 65, 0.7)',
            transform: 'scale(1.02)'
          },
        },
        'error-pulse': {
          '0%, 100%': {
            textShadow: '0 0 3px #FF0000, 0 0 8px #FF0000, 0 0 15px rgba(255, 0, 0, 0.6), 0 0 30px rgba(255, 0, 0, 0.4)',
            transform: 'scale(1)'
          },
          '50%': {
            textShadow: '0 0 5px #FF0000, 0 0 12px #FF0000, 0 0 25px rgba(255, 0, 0, 0.8), 0 0 40px rgba(255, 0, 0, 0.6), 0 0 60px rgba(255, 0, 0, 0.4)',
            transform: 'scale(1.05)'
          },
        },
        'amber-pulse': {
          '0%, 100%': {
            textShadow: '0 0 4px rgba(255, 191, 0, 1), 0 0 10px rgba(255, 191, 0, 0.7), 0 0 18px rgba(255, 191, 0, 0.4)'
          },
          '50%': {
            textShadow: '0 0 6px rgba(255, 215, 0, 1), 0 0 14px rgba(255, 215, 0, 0.9), 0 0 25px rgba(255, 215, 0, 0.6)'
          },
        },
        typewriter: {
          'from': { width: '0' },
          'to': { width: '100%' },
        },
        'fade-in': {
          'from': {
            opacity: '0',
            transform: 'translateY(10px)',
          },
          'to': {
            opacity: '1',
            transform: 'translateY(0)',
          },
        },
        'scan-sweep': {
          'from': { left: '-100%' },
          'to': { left: '100%' },
        },
        'glow-pulse': {
          '0%, 100%': {
            filter: 'drop-shadow(0 0 3px rgba(0, 255, 65, 0.8)) drop-shadow(0 0 8px rgba(0, 255, 65, 0.6)) drop-shadow(0 0 12px rgba(0, 255, 65, 0.4))'
          },
          '50%': {
            filter: 'drop-shadow(0 0 5px rgba(0, 255, 65, 1)) drop-shadow(0 0 12px rgba(0, 255, 65, 0.8)) drop-shadow(0 0 18px rgba(0, 255, 65, 0.6))'
          },
        },
        'screen-flicker': {
          '0%': { opacity: '0.75' },
          '5%': { opacity: '0.73' },
          '10%': { opacity: '0.75' },
          '15%': { opacity: '0.72' },
          '20%': { opacity: '0.75' },
          '50%': { opacity: '0.75' },
          '55%': { opacity: '0.74' },
          '100%': { opacity: '0.75' },
        },
        'scanlines-move': {
          '0%': { transform: 'translateY(0)' },
          '100%': { transform: 'translateY(4px)' },
        },
      },
      boxShadow: {
        'terminal-glow': '0 0 15px rgba(0, 255, 65, 0.35), inset 0 0 15px rgba(0, 255, 65, 0.06)',
        'terminal-glow-strong': '0 0 25px rgba(0, 255, 65, 0.5), inset 0 0 20px rgba(0, 255, 65, 0.1)',
      },
    },
  },
  plugins: [],
};
export default config;
