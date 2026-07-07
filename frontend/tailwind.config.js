/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Backchannel brand palette (matches site/style.css): teal accent on slate neutrals
        brand: {
          teal: "#0d9488",
          "teal-dark": "#0f766e",
          "teal-light": "#2dd4bf",
          amber: "#f59e0b",
          gray: "#475569",
          "dark-gray": "#0f172a",
          "mid-gray": "#64748b",
          "light-gray-1": "#e2e8f0",
          "light-gray-2": "#f8fafc",
        },
      },
      fontFamily: {
        display: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
        body: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
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
