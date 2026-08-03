import type { Config } from "tailwindcss";

// WakiliAI brand: deep navy + gold accent, warm paper background.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#0A1F3C",
          light: "#12305C",
          lighter: "#1C4680",
        },
        gold: {
          DEFAULT: "#C9A227",
          light: "#E3C55C",
          dim: "#8F7418",
        },
        paper: "#F7F4EC",
        ink: "#1B2430",
      },
      fontFamily: {
        display: ["Georgia", "Cambria", "'Times New Roman'", "serif"],
      },
    },
  },
  plugins: [],
};
export default config;
