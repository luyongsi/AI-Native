export const tokens = {
  colors: {
    brand: {
      50: '#eff6ff', 100: '#dbeafe', 200: '#bfdbfe', 300: '#93c5fd',
      400: '#60a5fa', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8',
      800: '#1e40af', 900: '#1e3a5f',
      primary: '#3b82f6',
      primaryHover: '#2563eb',
      primaryLight: '#93c5fd',
      primaryDark: '#1d4ed8',
    },
    surface: {
      bg: '#0f172a',      // slate-900
      card: '#1e293b',    // slate-800
      hover: '#334155',   // slate-700
      border: '#334155',  // slate-700
      raised: '#1e293b',
    },
    text: {
      primary: '#f1f5f9',   // slate-100
      secondary: '#94a3b8', // slate-400
      muted: '#64748b',     // slate-500
      inverse: '#0f172a',
    },
    status: {
      success: '#22c55e',
      error: '#ef4444',
      warning: '#f59e0b',
      info: '#3b82f6',
      running: '#8b5cf6',
      idle: '#64748b',
    },
    gates: {
      gate0: '#8b5cf6',
      gate1: '#3b82f6',
      gate2: '#06b6d4',
      gate3: '#10b981',
    }
  },
  typography: {
    fontFamily: {
      sans: "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif",
      mono: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
    },
    fontSize: {
      xs: '0.75rem', sm: '0.8125rem', base: '0.875rem',
      lg: '1rem', xl: '1.125rem', '2xl': '1.25rem', '3xl': '1.5rem',
    },
    fontWeight: { normal: 400, medium: 500, semibold: 600, bold: 700 },
    lineHeight: { tight: 1.25, normal: 1.5, relaxed: 1.75 },
  },
  spacing: {
    0: '0', 1: '0.25rem', 2: '0.5rem', 3: '0.75rem', 4: '1rem',
    5: '1.25rem', 6: '1.5rem', 8: '2rem', 10: '2.5rem', 12: '3rem', 16: '4rem',
  },
  radii: {
    none: '0', sm: '0.25rem', md: '0.375rem', lg: '0.5rem',
    xl: '0.75rem', '2xl': '1rem', full: '9999px',
  },
  shadows: {
    sm: '0 1px 2px 0 rgba(0,0,0,0.3)',
    md: '0 4px 6px -1px rgba(0,0,0,0.4)',
    lg: '0 10px 15px -3px rgba(0,0,0,0.5)',
    xl: '0 20px 25px -5px rgba(0,0,0,0.6)',
  },
  transitions: { fast: '150ms ease', normal: '200ms ease', slow: '300ms ease' },
  zIndex: { base: 0, dropdown: 1000, sticky: 1100, modal: 1300, toast: 1400, tooltip: 1500 },
} as const;

export type DesignTokens = typeof tokens;
