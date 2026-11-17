import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { LANGUAGE_BY_CODE, isLanguage, type Language } from "@/lib/languages";
import { en, type Catalog, type Key } from "./en";

const STORAGE_KEY = "vidhi-lang";
const catalogs = import.meta.glob<{ default: Catalog }>("./locales/*.ts");

interface I18n {
  lang: string;
  language: Language;
  setLang: (code: string) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
}

const Ctx = createContext<I18n | null>(null);

function initialLang(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (isLanguage(saved)) return saved;
  } catch {
    /* storage can be blocked: fall through */
  }
  const guess = (navigator.language || "en").toLowerCase().split("-")[0];
  return isLanguage(guess) ? guess : "en";
}

/**
 * Chooses the language of the buttons, menus and headings. English is always the fallback for any missing word, and the
 * right font for the script (and right-to-left direction for Urdu, Kashmiri and Sindhi) is loaded only when needed.
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<string>(initialLang);
  const [catalog, setCatalog] = useState<Catalog>({});
  const language = LANGUAGE_BY_CODE.get(lang) ?? LANGUAGE_BY_CODE.get("en")!;

  useEffect(() => {
    let live = true;
    document.documentElement.lang = lang;
    document.documentElement.dir = language.dir;
    void language.font?.();
    const loader = catalogs[`./locales/${lang}.ts`];
    if (lang === "en" || !loader) setCatalog({});
    else
      loader()
        .then((m) => live && setCatalog(m.default))
        .catch(() => live && setCatalog({}));
    return () => {
      live = false;
    };
  }, [lang, language]);

  const setLang = useCallback((code: string) => {
    if (!isLanguage(code)) return;
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch {
      /* the choice still applies for this visit */
    }
    setLangState(code);
  }, []);

  const t = useCallback(
    (key: Key, vars?: Record<string, string | number>) => {
      let s: string = catalog[key] ?? en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
      return s;
    },
    [catalog],
  );

  const value = useMemo(() => ({ lang, language, setLang, t }), [lang, language, setLang, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n must be used inside <I18nProvider>");
  return v;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSafeT(): I18n["t"] {
  // for the last-resort screens (error fallback, offline notice): they must still render, in English, if no provider is above them
  const v = useContext(Ctx);
  return v ? v.t : (key) => en[key] ?? key;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useT() {
  return useI18n().t;
}
