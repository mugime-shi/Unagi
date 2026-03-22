/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── Deep Sea theme (α: 深海回遊) ──
        // 元のグレーに戻すには下のブロックと入れ替える
        sea: {
          950: "#060e1f",
          900: "#0a1628",
          800: "#122240",
          700: "#1a3058",
        },
        // ── Original Gray theme ──
        // sea: {
        //   950: "#030712",
        //   900: "#111827",
        //   800: "#1f2937",
        //   700: "#374151",
        // },
      },
    },
  },
  plugins: [],
};
