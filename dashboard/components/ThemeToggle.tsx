"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

function readTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem("loopwire-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setTheme(readTheme()));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  function changeTheme() {
    const next: Theme = (theme ?? readTheme()) === "dark" ? "light" : "dark";
    const apply = () => {
      document.documentElement.dataset.theme = next;
      window.localStorage.setItem("loopwire-theme", next);
      setTheme(next);
    };

    if ("startViewTransition" in document && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.startViewTransition(apply);
    } else {
      apply();
    }
  }

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={changeTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      aria-pressed={isDark}
    >
      <span className="theme-toggle-track" aria-hidden>
        <svg viewBox="0 0 24 24" className="theme-icon theme-icon-sun" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <circle cx="12" cy="12" r="3.5" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42" />
        </svg>
        <svg viewBox="0 0 24 24" className="theme-icon theme-icon-moon" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <path d="M20.4 15.3A8.5 8.5 0 0 1 8.7 3.6 8.5 8.5 0 1 0 20.4 15.3Z" />
        </svg>
        <span className="theme-toggle-thumb" />
      </span>
      <span className="sr-only">{isDark ? "Dark theme active" : "Light theme active"}</span>
    </button>
  );
}
