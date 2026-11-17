import { useState } from "react";
import { Check, Globe, Laptop, Moon, Sun } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LANGUAGES } from "@/lib/languages";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { apiPatch } from "@/lib/api";

/** Remembers the choice on the account (best effort) so it follows the person to another phone or computer. */
function remember(body: { language?: string; theme?: string }) {
  void apiPatch("/auth/preferences", body).catch(() => undefined); // signed-out visitors simply keep it in this browser
}

/** The list of all 22 languages (plus English), each written in its own script. */
export function LanguageList({ onPick }: { onPick?: () => void }) {
  const { lang, setLang, t } = useI18n();
  return (
    <div>
      <ul className="grid max-h-[22rem] grid-cols-2 gap-1 overflow-y-auto pr-1" aria-label={t("set.language")}>
        {LANGUAGES.map((l) => (
          <li key={l.code}>
            <button
              aria-current={lang === l.code ? "true" : undefined}
              onClick={() => {
                setLang(l.code);
                remember({ language: l.code });
                onPick?.();
              }}
              data-testid={`lang-${l.code}`}
              dir={l.dir}
              className={`flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
                lang === l.code ? "bg-primary/10 text-foreground" : "text-muted-foreground"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate text-foreground">{l.native}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {l.english}
                  {l.quality === "core" ? " · Beta" : ""}
                </span>
              </span>
              {lang === l.code && <Check className="size-4 shrink-0 text-primary" />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A small globe button for the header: opens the language list. */
export function LanguageMenu() {
  const { language, t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            className="flex h-8 items-center gap-1.5 rounded-full border border-border px-2.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            aria-label={`${t("set.language")}: ${language.native}`}
            data-testid="language-menu"
          />
        }
      >
        <Globe className="size-3.5" />
        <span className="hidden sm:inline">{language.native}</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(92vw,26rem)] p-3" aria-label={t("set.language")}>
        <p className="px-1 pb-1 text-xs uppercase tracking-wider text-muted-foreground">{t("set.language")}</p>
        <LanguageList onPick={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
}

const OPTIONS: { value: ThemeChoice; icon: typeof Sun; key: "theme.dark" | "theme.light" | "theme.system" }[] = [
  { value: "dark", icon: Moon, key: "theme.dark" },
  { value: "light", icon: Sun, key: "theme.light" },
  { value: "system", icon: Laptop, key: "theme.system" },
];

/** Dark, light, or follow the device. */
export function ThemePicker() {
  const { choice, setChoice } = useTheme();
  const { t } = useI18n();
  return (
    <div className="inline-flex rounded-xl border border-border p-0.5" role="radiogroup" aria-label={t("set.theme")}>
      {OPTIONS.map(({ value, icon: Icon, key }) => (
        <button
          key={value}
          role="radio"
          aria-checked={choice === value}
          onClick={() => {
            setChoice(value);
            remember({ theme: value });
          }}
          data-testid={`theme-${value}`}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors ${
            choice === value ? "bg-primary/15 text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Icon className="size-4" />
          {t(key)}
        </button>
      ))}
    </div>
  );
}

/** A one-tap sun/moon button for the header. */
export function ThemeToggle() {
  const { resolved, setChoice } = useTheme();
  const { t } = useI18n();
  const next = resolved === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => {
        setChoice(next);
        remember({ theme: next });
      }}
      className="grid size-8 place-items-center rounded-full border border-border text-muted-foreground transition-colors hover:text-foreground"
      aria-label={`${t("set.theme")}: ${t(next === "dark" ? "theme.dark" : "theme.light")}`}
      data-testid="theme-toggle"
    >
      {resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

/** The Settings section: theme and language together. */
export function AppearanceSection() {
  const { t, language } = useI18n();
  return (
    <section className="glass rounded-lg p-5" data-testid="settings-appearance">
      <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">{t("set.appearance")}</h2>
      <div className="mt-4">
        <p className="mb-2 text-sm">{t("set.theme")}</p>
        <ThemePicker />
      </div>
      <div className="mt-5">
        <p className="mb-2 text-sm">{t("set.language")}</p>
        <LanguageList />
        <p className="mt-3 text-xs text-muted-foreground">{t("lang.note")}</p>
        {language.quality === "core" && <p className="mt-1 text-xs" style={{ color: "#F0A63A" }}>{t("lang.beta")}</p>}
      </div>
    </section>
  );
}
