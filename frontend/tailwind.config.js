/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        mosaic: {
          bg: "#0b0f17",
          panel: "#111827",
          border: "#1f2937",
          accent: "#22d3ee",
          long: "#10b981",
          short: "#ef4444",
          pair: "#3b82f6",
          warn: "#f59e0b",
          mute: "#94a3b8",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
