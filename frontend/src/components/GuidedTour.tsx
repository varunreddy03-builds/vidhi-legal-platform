import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useHelp } from "@/lib/help/useHelp";
import { useI18n } from "@/lib/i18n/I18nProvider";

const KEY = "vidhi-tour"; // remembers that the tour was seen or skipped (listed on the Cookies page)
export const OPEN_TOUR = "vidhi-open-tour";

/** A short first-run walk-through on the home screen, in the person's language where there is help text for it. Shown once; "Take a quick tour" reopens it. */
export default function GuidedTour() {
  const { lang } = useI18n();
  const h = useHelp(lang);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  // The tour never opens by itself (owner, 2026-10-31): it opens only from "Take a quick tour" on Home, under More, or in the help centre.
  useEffect(() => {
    const again = () => { setStep(0); setOpen(true); };
    window.addEventListener(OPEN_TOUR, again);
    return () => window.removeEventListener(OPEN_TOUR, again);
  }, []);

  const finish = () => {
    try {
      localStorage.setItem(KEY, "done");
    } catch {
      /* the tour may show again next visit */
    }
    setOpen(false);
  };
  const last = step === h.tour.length - 1;
  const t = h.tour[step];
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) finish(); }}>
      <DialogContent data-testid="guided-tour">
        <DialogHeader>
          <DialogTitle>{t.title}</DialogTitle>
        </DialogHeader>
        <p className="text-sm">{t.text}</p>
        <p className="text-xs text-muted-foreground">{h.ui.step.replace("{n}", String(step + 1)).replace("{total}", String(h.tour.length))}</p>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={finish} data-testid="tour-skip">{h.ui.skip}</Button>
          {step > 0 && <Button variant="outline" size="sm" onClick={() => setStep(step - 1)}>{h.ui.back}</Button>}
          <Button size="sm" onClick={() => (last ? finish() : setStep(step + 1))} data-testid="tour-next">{last ? h.ui.done : h.ui.next}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}