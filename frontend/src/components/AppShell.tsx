import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft,
  Bell,
  FileText,
  Gavel,
  HandCoins,
  LayoutDashboard,
  Landmark,
  Library,
  Home,
  CalendarDays,
  LifeBuoy,
  ShieldCheck,
  Ellipsis,
  PanelLeftClose,
  PanelLeft,
  Scale,
  Search,
  Settings,
  Wrench,
} from "lucide-react";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import CommandPalette from "@/components/CommandPalette";
import GuidedTour from "@/components/GuidedTour";
import MoreSheet from "@/components/MoreSheet";
import OfflineBanner from "@/components/OfflineBanner";
import { Button } from "@/components/ui/button";
import { useMe, useEntitlement, useLogo } from "@/lib/useMe";
import { useLawDrafts } from "@/lib/useLawDrafts";
import { endSession } from "@/lib/session";
import { useI18n, useT } from "@/lib/i18n/I18nProvider";
import { useTheme } from "@/lib/theme";
import PilotBanner from "@/components/PilotBanner";
import type { Key } from "@/lib/i18n/en";
import AccountMenu from "@/components/AccountMenu";

type Item = { id: string; key: Key; to: string; icon: typeof Gavel; action?: "search"; also?: string[] };
type Cluster = { group: Key; items: Item[] };

// VIDHI has two main parts, Legal Intelligence and Legal Katalyst. Legal Recovery is a small free option under "More".
const NAV_CLUSTERS: Cluster[] = [
  {
    group: "grp.workspace",
    items: [
      { id: "home", key: "nav.home", to: "/start", icon: Home },
      { id: "dates", key: "nav.dates", to: "/deadlines", icon: CalendarDays },
    ],
  },
  {
    group: "grp.intelligence",
    items: [
      { id: "intelligence", key: "nav.intelligence", to: "/intelligence", icon: Scale },
      { id: "research", key: "nav.research", to: "/research", icon: Search },
      { id: "matters", key: "nav.matters", to: "/matters", icon: Gavel },
      { id: "drafts", key: "nav.drafts", to: "/drafts", icon: FileText },
      { id: "law", key: "nav.law", to: "/law", icon: Library },
      { id: "judgments", key: "nav.judgments", to: "/judgments", icon: Landmark },
      { id: "legaldir", key: "nav.legaldir", to: "/legal-directory", icon: Landmark },
    ],
  },
  {
    group: "grp.katalyst",
    items: [{ id: "toolkit", key: "nav.toolkit", to: "/katalyst", icon: Wrench }],
  },
  {
    group: "grp.more",
    items: [
      { id: "dashboard", key: "nav.dashboard", to: "/dashboard", icon: LayoutDashboard },
      { id: "activity", key: "nav.activity", to: "/activity", icon: Bell },
      { id: "recovery", key: "nav.recovery", to: "/recovery", icon: HandCoins },
    ],
  },
  {
    group: "grp.system",
    items: [
      { id: "support", key: "nav.support", to: "/support", icon: LifeBuoy },
      { id: "settings", key: "nav.settings", to: "/settings", icon: Settings },
    ],
  },
];

// On a phone four actions plus "More" sit in the bottom bar; everything else is under "More" (components/MoreSheet.tsx).
const MOBILE_ITEMS: Item[] = [
  { id: "home", key: "nav.home", to: "/start", icon: Home },
  { id: "intelligence", key: "nav.intelligence", to: "/intelligence", icon: Scale, also: ["/ask", "/research", "/matters", "/drafts"] },
  { id: "toolkit", key: "nav.toolkit", to: "/katalyst", icon: Wrench },
  { id: "dates", key: "nav.dates", to: "/deadlines", icon: CalendarDays },
];

export default function AppShell({
  children,
  intensity = "ambient",
  title,
  back,
}: {
  children: ReactNode;
  intensity?: "ambient" | "active";
  title?: string;
  back?: string;
}) {
  const t = useT();
  const { setLang } = useI18n();
  const { setChoice } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  useEffect(() => {
    const before = document.title;
    document.title = title ? `${title} - VIDHI` : "VIDHI";  // the browser tab and the recent-apps list say where you are
    return () => {
      document.title = before;
    };
  }, [title]);
  const { data: me, isLoading } = useMe();
  const { data: ent } = useEntitlement();
  const { data: logo } = useLogo();
  const location = useLocation();
  const navigate = useNavigate();

  // There is one navigation now. Legal Recovery pages only change the accent colour and the notice at the top.
  const division: "intelligence" | "recovery" = location.pathname.startsWith("/recovery") ? "recovery" : "intelligence";
  const { data: lawDrafts } = useLawDrafts(!!me);
  const lawOff = lawDrafts?.enabled === false;
  const { enabled: recoveryOn } = useRecoveryEnabled();
  const clusters = NAV_CLUSTERS.map((c) => ({ ...c, items: c.items.filter((i) => !(i.id === "law" && lawOff) && !(i.id === "recovery" && !recoveryOn)) }));

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // First visit on this device: take the language and theme saved on the account.
  useEffect(() => {
    if (!me) return;
    try {
      if (me.language && !localStorage.getItem("vidhi-lang")) setLang(me.language);
      if (me.theme && !localStorage.getItem("vidhi-theme")) setChoice(me.theme);
    } catch {
      /* blocked storage: the account value is simply not applied */
    }
  }, [me, setLang, setChoice]);

  useEffect(() => {
    if (!isLoading && me === null) navigate("/login", { replace: true });
    if (me?.role === "CLIENT") navigate("/portal", { replace: true }); // a client of the firm only ever sees the portal
  }, [isLoading, me, navigate]);

  async function signOut() {
    try {
      await endSession();
    } catch {
      toast.error("Could not sign out. Check your connection and try again.");
      return; // still signed in: do not pretend otherwise
    }
    setMoreOpen(false);
    navigate("/login", { replace: true });
  }

  return (
    <div className="relative min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:ring-2 focus:ring-ring"
        data-testid="skip-to-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <NervousSystemBackground intensity={intensity} />
      <div className="relative z-10 flex min-h-screen">
        <aside
          aria-label="Sidebar"
          className={`hidden shrink-0 border-r border-border bg-sidebar/70 backdrop-blur-md transition-[width] duration-300 md:block ${
            collapsed ? "w-16" : "w-60"
          }`}
          data-testid="app-sidebar"
        >
          <div className="flex h-14 items-center gap-2 px-4">
            {logo?.data_url ? (
              <img
                src={logo.data_url}
                alt="Firm logo"
                className="size-6 shrink-0 rounded object-contain"
                data-testid="firm-logo-sidebar"
              />
            ) : (
              <span
                className="text-lg"
                style={{ color: division === "recovery" ? "#C8A96B" : "#5B8CFF" }}
              >
                ◈
              </span>
            )}
            {!collapsed && (
              <span className="font-heading text-sm tracking-[0.2em] text-foreground">VIDHI</span>
            )}
          </div>
          <nav className="mt-2 space-y-4 px-2" aria-label="Main">
            {clusters.map((cluster) => (
              <div key={cluster.group}>
                {!collapsed && (
                  <p className="px-2 pb-1 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    {t(cluster.group)}
                  </p>
                )}
                {cluster.items.map((item) => {
                  const active =
                    item.to === "/recovery"
                      ? location.pathname.startsWith("/recovery")
                      : location.pathname.startsWith(item.to);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      data-testid={`nav-${item.id}`}
                      className={`flex items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors duration-200 ${
                        active
                          ? "bg-accent text-foreground shadow-[inset_2px_0_0_var(--color-neural)]"
                          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                      }`}
                    >
                      <Icon className="size-4 shrink-0" />
                      {!collapsed && <span>{t(item.key)}</span>}
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>
          {me?.platform_admin && (
            <div className="mt-4 px-2">
              <Link
                to="/admin"
                data-testid="nav-admin"
                className={`flex items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors duration-200 ${
                  location.pathname.startsWith("/admin") ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                }`}
              >
                <ShieldCheck className="size-4 shrink-0" />
                {!collapsed && <span>Admin console</span>}
              </Link>
            </div>
          )}
          <div className="mt-3 px-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCollapsed((v) => !v)}
              data-testid="sidebar-collapse-toggle"
              className="w-full justify-start text-muted-foreground"
            >
              {collapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
              {!collapsed && <span className="ml-2">{t("nav.collapse")}</span>}
            </Button>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-[var(--safe-top)] z-20 flex h-14 items-center gap-3 border-b border-border bg-background/70 px-4 backdrop-blur-md">
            {back && (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => navigate(back)}
                data-testid="app-back-button"
                aria-label={t("common.back")}
              >
                <ArrowLeft className="size-4" />
              </Button>
            )}
            {logo?.data_url && (
              <img
                src={logo.data_url}
                alt="Firm logo"
                className="size-7 shrink-0 rounded object-contain md:hidden"
                data-testid="firm-logo-header"
              />
            )}
            <h1 className="truncate font-heading text-sm text-foreground" data-testid="page-title">
              {title ?? "VIDHI"}
            </h1>
            <div className="ml-auto flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPaletteOpen(true)}
                data-testid="open-command-palette"
                className="gap-2 text-muted-foreground"
              >
                <Search className="size-3.5" />
                <span className="sr-only sm:not-sr-only md:sr-only lg:not-sr-only">{t("header.search")}</span>
                <kbd aria-hidden="true" className="hidden rounded border border-border px-1 text-[10px] lg:inline">
                  ⌘K
                </kbd>
              </Button>
              {me && <AccountMenu name={me.full_name} organization={me.organization_name} plan={division === "intelligence" && ent ? (ent.plan === "PRO" ? "PRO" : "FREE") : undefined} onSignOut={signOut} />}
            </div>
          </header>

          {me?.two_step_required && !me.two_factor && (
            <div className="border-b px-4 py-2 text-center text-xs" style={{ color: "#F0A63A", background: "rgba(240,166,58,0.12)", borderColor: "rgba(240,166,58,0.4)" }} role="alert" data-testid="two-step-banner">
              {me.two_step_due_at && new Date(me.two_step_due_at) < new Date()
                ? "Two-step sign-in is now required for owners and admins of a team. "
                : `Two-step sign-in will be required for owners and admins of a team from ${me.two_step_due_at ? new Date(me.two_step_due_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "soon"}. `}
              <Link to="/settings" className="underline underline-offset-4">Turn it on in Settings</Link>
            </div>
          )}
          <OfflineBanner />
          <aside
            aria-label="Notice"
            className="border-b border-border px-4 py-1 text-center text-[11px] leading-snug text-muted-foreground"
            data-testid="disclaimer-banner"
          >
            {division === "recovery" ? t("banner.recovery") : t("banner.intel")}
          </aside>

          <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 p-4 pb-24 outline-none md:p-8 md:pb-8">
            <PilotBanner show={!!me?.pilot} />
            {children}
          </main>

          <nav className="sticky bottom-0 z-20 flex border-t border-border bg-background/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden" aria-label="Main (phone)" data-testid="mobile-nav">
            {MOBILE_ITEMS.map((item) => {
              const Icon = item.icon;
              const path = item.to.split("?")[0];
              const active = !item.action && [path, ...(item.also ?? [])].some((p) => location.pathname.startsWith(p));
              const cls = `flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 text-[9.5px] ${active ? "text-neural" : "text-muted-foreground"}`;
              const style = active ? { color: division === "recovery" ? "#C8A96B" : "#5B8CFF" } : undefined;
              const label = <span className="line-clamp-2 max-w-full text-center leading-[1.15]">{t(item.key)}</span>; // up to two lines ("Legal" over "Intelligence"), never half a glyph; the full text is the accessible name and the tooltip
              return item.action ? (
                <button key={item.id} type="button" onClick={() => setPaletteOpen(true)} data-testid={`mobile-nav-${item.id}`} className={cls} aria-label={t(item.key)} title={t(item.key)}>
                  <Icon className="size-4" />
                  {label}
                </button>
              ) : (
                <Link key={item.id} to={item.to} data-testid={`mobile-nav-${item.id}`} className={cls} style={style} aria-label={t(item.key)} title={t(item.key)}>
                  <Icon className="size-4" />
                  {label}
                </Link>
              );
            })}
            <button type="button" onClick={() => setMoreOpen(true)} data-testid="mobile-nav-more" aria-label={t("nav.more")} className="flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 text-[9.5px] text-muted-foreground">
              <Ellipsis className="size-4" />
              <span className="block max-w-full truncate text-center leading-[1.15]">{t("nav.more")}</span>
            </button>
          </nav>
        </div>
      </div>
      <MoreSheet
        open={moreOpen}
        onOpenChange={setMoreOpen}
        isAdmin={!!me?.platform_admin}
        orgName={me?.organization_name}
        plan={ent?.plan}
        onSearch={() => setPaletteOpen(true)}
        onSignOut={signOut}
      />
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <GuidedTour />
    </div>
  );
}
