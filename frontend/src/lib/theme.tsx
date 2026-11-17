import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemeChoice = "dark" | "light" | "system";
const STORAGE_KEY = "vidhi-theme";

interface ThemeCtx {
  choice: ThemeChoice;
  resolved: "dark" | "light";
  setChoice: (c: ThemeChoice) => void;
}
const Ctx = createContext<ThemeCtx | null>(null);

function saved(): ThemeChoice {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "dark" || v === "light" || v === "system") return v;
  } catch {
    /* blocked storage: default below */
  }
  return "dark"; // the original look is the default
}

const prefersLight = () => window.matchMedia?.("(prefers-color-scheme: light)").matches ?? false;

export function applyTheme(choice: ThemeChoice): "dark" | "light" {
  const resolved = choice === "system" ? (prefersLight() ? "light" : "dark") : choice;
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.classList.toggle("light", resolved === "light");
  return resolved;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(saved);
  const [resolved, setResolved] = useState<"dark" | "light">(() => applyTheme(saved()));

  useEffect(() => {
    setResolved(applyTheme(choice));
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const on = () => setResolved(applyTheme("system"));
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [choice]);

  const setChoice = useCallback((c: ThemeChoice) => {
    try {
      localStorage.setItem(STORAGE_KEY, c);
    } catch {
      /* the choice still applies for this visit */
    }
    setChoiceState(c);
  }, []);

  const value = useMemo(() => ({ choice, resolved, setChoice }), [choice, resolved, setChoice]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTheme must be used inside <ThemeProvider>");
  return v;
}
