import type { Config } from "tailwindcss";

const config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── 品牌色 ──
        ink: "var(--ink)",
        shell: "var(--shell)",
        paper: "var(--paper)",
        mint: "var(--mint)",
        coral: "var(--coral)",

        // ── Shadcn 语义色 ──
        background: "var(--background)",
        foreground: "var(--foreground)",

        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
      },

      borderRadius: {
        lg: "var(--radius)",                    // 8px
        md: "calc(var(--radius) - 2px)",        // 6px
        sm: "calc(var(--radius) - 4px)",        // 4px
        card: "1.25rem",                        // 20px — 大卡片
      },

      boxShadow: {
        float: "0 16px 40px -20px rgba(6, 37, 39, 0.55)",
        soft: "0 4px 24px -4px rgba(0,0,0,0.06), 0 2px 8px -2px rgba(0,0,0,0.04)",
      },

      fontFamily: {
        display: ["Sora", "sans-serif"],
        body: ["Noto Sans SC", "sans-serif"],
      },

      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-from-right": {
          from: { transform: "translateX(100%)" },
          to: { transform: "translateX(0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fade-in 0.3s ease-out",
        "slide-in-right": "slide-in-from-right 0.3s ease-out",
      },
    },
  },
  plugins: [],
} satisfies Config;

export default config;
