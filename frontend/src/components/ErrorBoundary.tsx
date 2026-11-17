import { Component, type ErrorInfo, type ReactNode } from "react";
import { useSafeT } from "@/lib/i18n/I18nProvider";

function Fallback() {
  const t = useSafeT();
  return (
    <div role="alert" data-testid="error-boundary" className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center text-foreground">
      <h1 className="font-heading text-xl">{t("err.title")}</h1>
      <p className="max-w-sm text-sm text-muted-foreground">{t("err.body")}</p>
      <div className="flex flex-wrap justify-center gap-3">
        <button type="button" className="btn-orbit rounded-full px-5 py-2 text-sm" onClick={() => window.location.reload()}>
          {t("err.reload")}
        </button>
        <a href="/start" className="rounded-full border border-border px-5 py-2 text-sm text-muted-foreground hover:text-foreground">
          {t("err.home")}
        </a>
      </div>
    </div>
  );
}

/**
 * The last safety net: if a screen crashes, the person sees a calm message with two ways out instead of a blank page.
 * Nothing about the error is sent anywhere or shown (it can contain personal text); it is only written to the browser console for whoever is debugging.
 */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("VIDHI screen error:", error.message, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <Fallback />;
  }
}
