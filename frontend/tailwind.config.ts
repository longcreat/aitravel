import type { Config } from "tailwindcss";

const config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "var(--ink)",
        shell: "var(--shell)",
        mint: "var(--mint)",
        coral: "var(--coral)",
        paper: "var(--paper)",
      },
      boxShadow: {
        float: "0 16px 40px -20px rgba(6, 37, 39, 0.55)",
      },
      borderRadius: {
        card: "1.25rem",
      },
      fontFamily: {
        display: ["Sora", "sans-serif"],
        body: ["Noto Sans SC", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;

export default config;
