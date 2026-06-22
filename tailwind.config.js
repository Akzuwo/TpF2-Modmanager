module.exports = {
  darkMode: "class",
  content: ["./web_static/**/*.html", "./web_static/**/*.js"],
  theme: {
    extend: {
      colors: {
        rail: "#202c38",
        pine: "#384959",
        mint: "#88BDF2",
        ember: "#c25f50"
      },
      boxShadow: {
        panel: "0 18px 54px rgba(11, 18, 16, 0.10)",
        "panel-dark": "0 22px 70px rgba(0, 0, 0, 0.32)"
      },
      keyframes: {
        "fade-slide": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        "modal-pop": {
          "0%": { opacity: "0", transform: "translateY(12px) scale(.98)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" }
        },
        "soft-pulse": {
          "0%, 100%": { opacity: "0.42" },
          "50%": { opacity: "0.95" }
        }
      },
      animation: {
        "fade-slide": "fade-slide 220ms ease both",
        "modal-pop": "modal-pop 220ms cubic-bezier(.2,.8,.2,1) both",
        "soft-pulse": "soft-pulse 1.9s ease-in-out infinite"
      }
    }
  },
  plugins: []
};
