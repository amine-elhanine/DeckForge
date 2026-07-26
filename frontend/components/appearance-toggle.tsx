"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

const STORAGE_KEY = "deckforge-appearance";

/** Light/dark switch for the application chrome (deck themes are separate). */
export function AppearanceToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? "dark" : "light");
    } catch {
      /* private browsing */
    }
  };

  return (
    <button
      onClick={toggle}
      className="btn btn-ghost h-8 w-8 p-0"
      aria-label={dark ? "Switch to light appearance" : "Switch to dark appearance"}
      title="Toggle appearance"
    >
      {dark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}
