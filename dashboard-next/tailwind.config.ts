import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#151816",
        paper: "#f7f2e8",
        panel: "#fffaf0",
        moss: "#36493b",
        signal: "#08b7a6",
        amber: "#f1a340",
        ember: "#e85d4a",
        graphite: "#27302d",
      },
      boxShadow: {
        panel: "0 22px 60px rgba(31, 37, 34, 0.16)",
        glow: "0 0 0 1px rgba(8, 183, 166, 0.15), 0 18px 46px rgba(8, 183, 166, 0.18)",
      },
      backgroundImage: {
        "radial-grid":
          "radial-gradient(circle at 20% 20%, rgba(8,183,166,.18), transparent 28%), radial-gradient(circle at 80% 0%, rgba(241,163,64,.22), transparent 24%), linear-gradient(135deg, #f7f2e8 0%, #efe6d3 45%, #e3dac8 100%)",
      },
      fontFamily: {
        display: ["Fraunces", "Georgia", "serif"],
        body: ["Manrope", "Aptos", "Verdana", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
