import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  Bell,
  FlaskConical,
  Gavel,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  Route,
  HandCoins,
  Scale,
  Scroll,
  Search,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { LanguageList, ThemePicker } from "@/components/AppearanceControls";
import { OPEN_TOUR } from "@/components/GuidedTour";
import { LegalLinks } from "@/lib/legal";
import { useI18n, useT } from "@/lib/i18n/I18nProvider";
import { useHelp } from "@/lib/help/useHelp";
import { useSample } from "@/lib/useSample";

const row = "flex min-h-12 w-full items-center gap-3 rounded-lg px-3 text-left text-sm text-foreground transition-colors hover:bg-accent";

/** Everything that is not one of the five main actions on a phone: one place, one button. */
export default function MoreSheet({
  open,
  onOpenChange,
  isAdmin,
  orgName,
  plan,
  onSearch,
  onSignOut,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  isAdmin: boolean;
  orgName?: string;
  plan?: string;
  onSearch: () => void;
  onSignOut: () => void;
}) {
  const t = useT();
  const { enabled: recoveryOn } = useRecoveryEnabled();
  const { lang } = useI18n();
  const h = useHelp(lang);
  const sample = useSample(h.ui.sampleMade);
  const close = () => onOpenChange(false);
  const go = (to: string, label: ReactNode, Icon: typeof Gavel, id: string) => (
    <Link to={to} onClick={close} className={row} data-testid={`more-${id}`}>
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      {label}
    </Link>
  );
  const act = (label: ReactNode, Icon: typeof Gavel, id: string, fn: () => void, disabled = false) => (
    <button
      type="button"
      className={row}
      disabled={disabled}
      data-testid={`more-${id}`}
      onClick={() => {
        close();
        fn();
      }}
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      {label}
    </button>
  );

  const goSub = (to: string, label: ReactNode, sub: string, Icon: typeof Gavel, id: string) => (
    <Link to={to} onClick={close} className={`${row} py-2`} data-testid={`more-${id}`}>
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <span className="block">
        <span className="block">{label}</span>
        <span className="block text-xs text-muted-foreground" data-testid={`more-${id}-sub`}>{sub}</span>
      </span>
    </Link>
  );

  const heading = (label: string) => <p className="px-3 pb-0.5 pt-3 text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-h-[85dvh] overflow-y-auto pb-[env(safe-area-inset-bottom)]" data-testid="more-sheet">
        <SheetHeader>
          <SheetTitle>{t("nav.more")}</SheetTitle>
        </SheetHeader>
        <div className="space-y-1 px-2 pb-4">
          {heading(t("more.askfind"))}
          {act(t("header.search"), Search, "search", onSearch)}
          {heading(t("more.work"))}
          {go("/dashboard", t("nav.dashboard"), LayoutDashboard, "dashboard")}
          {go("/activity", t("nav.activity"), Bell, "activity")}
          {go("/templates", t("more.templates"), Scroll, "templates")}
          {go("/clients", t("more.clients"), Users, "clients")}
          {go("/conflicts", t("more.conflicts"), Users, "conflicts")}
          {go("/legal", t("more.legal"), Scale, "legal")}
          {go("/lawyers", t("more.lawyers"), Gavel, "lawyers")}
          {recoveryOn && goSub("/recovery", t("nav.recovery"), t("more.recovery.sub"), HandCoins, "recovery")}
          {heading(t("more.help"))}
          {act(h.ui.tour, Route, "tour", () => window.dispatchEvent(new Event(OPEN_TOUR)))}
          {act(h.ui.sample, FlaskConical, "sample", () => sample.mutate(), sample.isPending)}
          {go("/help", h.ui.helpCentre, BookOpen, "help")}
          {go("/support", t("nav.support"), LifeBuoy, "support")}
          {heading(t("grp.account"))}
          {go("/settings", t("nav.settings"), Settings, "settings")}
          {isAdmin && go("/admin", t("more.admin"), ShieldCheck, "admin")}
        </div>
        <div className="space-y-3 border-t border-border px-4 py-4">
          <div>
            <p className="pb-1 text-xs uppercase tracking-wider text-muted-foreground">{t("set.theme")}</p>
            <ThemePicker />
          </div>
          <div>
            <p className="pb-1 text-xs uppercase tracking-wider text-muted-foreground">{t("set.language")}</p>
            <LanguageList onPick={close} />
          </div>
          <p className="text-xs text-muted-foreground" data-testid="more-org">
            {orgName}
            {plan ? ` · ${plan === "PRO" ? "PRO" : "FREE"}` : ""}
          </p>
          <button type="button" className={`${row} text-destructive`} onClick={onSignOut} data-testid="more-signout">
            <LogOut className="size-4 shrink-0" />
            {t("header.signOut")}
          </button>
          <LegalLinks />
          <p className="pt-1 text-[11px] text-muted-foreground" data-testid="app-version">VIDHI version {__APP_VERSION__}</p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
