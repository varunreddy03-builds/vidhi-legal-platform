import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, Globe, LogOut, Settings, User } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LanguageList, ThemePicker } from "@/components/AppearanceControls";
import { useI18n } from "@/lib/i18n/I18nProvider";

/** One calm menu in the top bar instead of a plan badge, an organisation name and a sign-out icon: who is signed in, the plan, theme, language, settings and sign out. */
export default function AccountMenu({ name, organization, plan, onSignOut }: { name: string; organization: string; plan?: "FREE" | "PRO"; onSignOut: () => void }) {
  const { language, t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            className="flex h-8 items-center gap-2 rounded-full border border-border pl-1 pr-2 text-xs text-muted-foreground transition-colors hover:text-foreground md:pr-2.5"
            aria-label={`${name}, ${organization}`}
            data-testid="account-menu"
          />
        }
      >
        <span className="grid size-6 place-items-center rounded-full bg-primary/15 text-foreground" aria-hidden="true">
          <User className="size-3.5" />
        </span>
        <span className="hidden max-w-[10rem] truncate lg:inline" data-testid="current-org">{organization}</span>
        <ChevronDown className="size-3.5" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(92vw,22rem)] p-3" aria-label={`${name}, ${organization}`}>
        <div className="px-1 pb-3">
          <p className="truncate text-sm text-foreground">{name}</p>
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="truncate">{organization}</span>
            {plan && (
              <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px]" data-testid="plan-badge">
                {plan}
              </span>
            )}
          </p>
        </div>
        <div className="border-t border-border py-3">
          <p className="mb-2 px-1 text-xs uppercase tracking-wider text-muted-foreground">{t("set.theme")}</p>
          <ThemePicker />
        </div>
        <details className="border-t border-border py-2" data-testid="account-language">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-1 py-2 text-sm text-foreground hover:bg-accent">
            <Globe className="size-4 text-muted-foreground" aria-hidden="true" />
            <span>{t("set.language")}</span>
            <span className="ml-auto text-xs text-muted-foreground" dir={language.dir}>{language.native}</span>
          </summary>
          <div className="pt-2">
            <LanguageList onPick={() => setOpen(false)} />
          </div>
        </details>
        <div className="border-t border-border pt-2">
          <Link to="/settings" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-1 py-2 text-sm text-foreground hover:bg-accent" data-testid="account-settings">
            <Settings className="size-4 text-muted-foreground" aria-hidden="true" />
            {t("nav.settings")}
          </Link>
          <button type="button" onClick={onSignOut} className="flex w-full items-center gap-2 rounded-lg px-1 py-2 text-left text-sm text-destructive hover:bg-accent" data-testid="sign-out-button">
            <LogOut className="size-4" aria-hidden="true" />
            {t("header.signOut")}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
