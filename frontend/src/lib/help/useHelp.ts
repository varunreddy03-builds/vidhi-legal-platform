import { useEffect, useMemo, useState } from "react";
import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import en from "./en";
import type { HelpContent } from "./types";

/** The languages the help centre and the tour exist in. Others fall back to English. Every one except English is an unreviewed translation. */
export const HELP_LANGUAGES = ["en", "hi", "te", "ta", "bn", "mr", "gu"] as const;
const loaders = import.meta.glob<{ default: HelpContent }>("./{bn,gu,hi,mr,ta,te}.ts"); // exactly the translated files: a plain "./*.ts" also pulled the test file (and the test runner with it) into the production build as a 259 KB chunk

export const hasHelp = (code: string) => (HELP_LANGUAGES as readonly string[]).includes(code);

// While Legal Recovery is switched off (backend RECOVERY_ENABLED) the help centre must not describe it. Product names are never translated, so the section title is the same in every language.
const RECOVERY_SECTION = "Legal Recovery";
const RECOVERY_SENTENCE = / Legal Recovery, under More, is for anyone owed money \([^)]*\)\./; // the one English sentence in the intro that advertises it; the other languages' intros still mention it (see PROJECT_MEMORY)

/** The help text for a language (English until it has loaded, and whenever there is none), without the Legal Recovery parts when Legal Recovery is off. */
export function useHelp(code: string): HelpContent {
  const raw = useHelpRaw(code);
  const { enabled } = useRecoveryEnabled();
  return useMemo(
    () => (enabled ? raw : { ...raw, sections: raw.sections.filter((s) => s.title !== RECOVERY_SECTION).map((s) => ({ ...s, items: s.items.map((i) => ({ ...i, a: i.a.replace(RECOVERY_SENTENCE, "") })) })) }),
    [raw, enabled],
  );
}

function useHelpRaw(code: string): HelpContent {
  const [content, setContent] = useState<HelpContent>(en);
  useEffect(() => {
    let live = true;
    const load = code !== "en" && hasHelp(code) ? loaders[`./${code}.ts`] : undefined;
    if (!load) setContent(en);
    else
      load()
        .then((m) => live && setContent(m.default))
        .catch(() => live && setContent(en));
    return () => {
      live = false;
    };
  }, [code]);
  return content;
}