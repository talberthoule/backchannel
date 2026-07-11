/** @type {import('tailwindcss').Config} */
const channel = (v) => `rgb(var(${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // Semantic tokens backed by CSS variables (see index.css). These swap
        // between light and dark; primitives never change.
        surface: channel("--surface"),
        canvas: channel("--canvas"),
        // Backchannel brand palette. Names kept for back-compat; values now
        // resolve through the semantic token layer so a theme swap re-skins
        // the whole app without touching components.
        brand: {
          teal: channel("--accent"),
          "teal-dark": channel("--accent-dark"),
          "teal-light": channel("--accent-light"),
          amber: channel("--accent-2"),
          gray: channel("--text-secondary"),
          "dark-gray": channel("--text-primary"),
          "mid-gray": channel("--text-tertiary"),
          "light-gray-1": channel("--border-subtle"),
          "light-gray-2": channel("--surface-muted"),
        },
      },
      fontFamily: {
        display: ["Inter Variable", "Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
        body: ["Inter Variable", "Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
      },
      keyframes: {
        "slide-in-right": {
          "0%": { transform: "translateX(1rem)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
      },
      animation: {
        "slide-in-right": "slide-in-right 0.3s ease-out",
      },
    },
  },
  plugins: [],
};
