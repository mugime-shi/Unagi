/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "var(--font-sans)",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        display: ["var(--font-display)", "Georgia", "Cambria", "serif"],
        mono: ["var(--font-mono)", "Menlo", "Monaco", "monospace"],
      },
      colors: {
        // ── Deep Sea theme (α: 深海回遊) ──
        // 既存コンポーネント互換用。新規コードは surface/content トークンを使う
        sea: {
          950: "#060e1f",
          900: "#0a1628",
          800: "#122240",
          700: "#1a3058",
        },
        // ── Semantic tokens (theme-aware via CSS variables) ──
        surface: {
          page: "var(--surface-page)",
          primary: "var(--surface-primary)",
          secondary: "var(--surface-secondary)",
          tertiary: "var(--surface-tertiary)",
        },
        content: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          muted: "var(--text-muted)",
          faint: "var(--text-faint)",
        },
      },
    },
  },
  plugins: [],
};
