"use client";

/**
 * ThemeToggle — Sun/Moon toggle for light/dark mode.
 *
 * Per design spec §10:
 * - Uses Tailwind `class` strategy (adds/removes `dark` class on <html>)
 * - Persists preference in localStorage under `floatchat-theme`
 * - Defaults to OS preference on first visit (`prefers-color-scheme`)
 */

import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";

type Theme = "light" | "dark";

function getSystemTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function getStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem("floatchat-theme");
  if (stored === "light" || stored === "dark") return stored;
  return null;
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  // On mount: apply stored or system preference
  useEffect(() => {
    const resolved = getStoredTheme() ?? getSystemTheme();
    setTheme(resolved);
    applyTheme(resolved);
    setMounted(true);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "light" ? "dark" : "light";
    setTheme(next);
    applyTheme(next);
    localStorage.setItem("floatchat-theme", next);
  };

  // Prevent hydration mismatch flash
  if (!mounted) {
    return (
      <button
        className="rounded-md p-2 text-muted-foreground"
        aria-label="Toggle theme"
        disabled
      >
        <Sun className="h-4 w-4" />
      </button>
    );
  }

  return (
    <button
      onClick={toggle}
      className="rounded-md p-2 text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
      aria-label={
        theme === "light" ? "Switch to dark mode" : "Switch to light mode"
      }
    >
      {theme === "light" ? (
        <Moon className="h-4 w-4" />
      ) : (
        <Sun className="h-4 w-4" />
      )}
    </button>
  );
}
