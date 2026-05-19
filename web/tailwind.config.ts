import type { Config } from "tailwindcss";

// Ported from the personal-site tokens at assets/style.css so the
// dashboard reads as a sibling page in the same design system.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper:       "#faf8f3",
        "paper-deep":"#f3efe3",
        panel:       "#ffffff",
        ink:         "#14161a",
        "ink-soft":  "#45494f",
        "ink-mute":  "#767a82",
        rule:        "#e6e1d3",
        "rule-strong":"#cfc8b6",
        accent:      "#1f3a5f",
        "accent-soft":"rgba(31, 58, 95, 0.08)",
        "accent-line":"rgba(31, 58, 95, 0.25)",
        warn:        "#b45309",
        ok:          "#2f6a4a",
        // Stop / red — not in the personal site palette directly;
        // pick a muted brick-red that lives comfortably with #1f3a5f.
        stop:        "#9b2c1f",
      },
      fontFamily: {
        display: ['"Inter Tight"', 'Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'sans-serif'],
        sans:    ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'sans-serif'],
        mono:    ['"JetBrains Mono"', '"SF Mono"', 'ui-monospace', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      borderRadius: {
        sm: "8px",
        md: "14px",
        lg: "22px",
      },
      boxShadow: {
        card:  "0 1px 0 rgba(20, 22, 26, 0.04), 0 18px 40px rgba(20, 22, 26, 0.05)",
        hover: "0 1px 0 rgba(20, 22, 26, 0.05), 0 24px 56px rgba(20, 22, 26, 0.08)",
      },
    },
  },
  plugins: [],
};
export default config;
