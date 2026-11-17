import { useEffect, useState } from "react";
import { useSafeT } from "@/lib/i18n/I18nProvider";

/** A slim notice while the device has no network, so a failed save is never a mystery. It disappears by itself when the connection returns. */
export default function OfflineBanner() {
  const t = useSafeT();
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  if (online) return null;
  return (
    <div role="status" data-testid="offline-banner" className="border-b border-border bg-muted px-4 py-1.5 text-center text-[12px] text-foreground">
      {t("offline.banner")}
    </div>
  );
}
