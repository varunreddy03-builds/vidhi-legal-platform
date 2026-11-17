import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Scale, Sparkles, Wrench } from "lucide-react";
import AppShell from "@/components/AppShell";
import Door from "@/components/brand/Door";
import InlineSearch from "@/components/InlineSearch";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiGet } from "@/lib/api";
import { useSample } from "@/lib/useSample";
import { OPEN_TOUR } from "@/components/GuidedTour";
import { useHelp } from "@/lib/help/useHelp";
import { useI18n, useT } from "@/lib/i18n/I18nProvider";
import { firstName } from "@/lib/plain";
import type { Matter } from "@/lib/types";
import { useMe } from "@/lib/useMe";

/** Three small links under the search box: the tour, a fictional sample matter to practise on, and the help centre (in the person's language where there is help text). */
function StartHelp() {
  const { lang } = useI18n();
  const h = useHelp(lang);
  const sample = useSample(h.ui.sampleMade);
  return (
    <section className="mt-6 hidden flex-wrap items-center md:flex justify-center gap-x-6 gap-y-2 text-sm text-muted-foreground" data-testid="start-help">
      <button className="underline underline-offset-4" onClick={() => window.dispatchEvent(new Event(OPEN_TOUR))} data-testid="start-tour">{h.ui.tour}</button>
      <button className="underline underline-offset-4" onClick={() => sample.mutate()} disabled={sample.isPending} data-testid="start-sample">{h.ui.sample}</button>
      <Link to="/help" className="underline underline-offset-4" data-testid="start-help-link">{h.ui.helpCentre}</Link>
    </section>
  );
}

/** The first screen after signing in: a question box, the two main parts of VIDHI, and a search box that works as you type. Legal Recovery lives under More. */
export default function Start() {
  const t = useT();
  const navigate = useNavigate();
  const { data: me } = useMe();
  const [q, setQ] = useState("");
  const matters = useQuery<Matter[]>({ queryKey: ["matters"], queryFn: () => apiGet<Matter[]>("/matters") });
  const caseCount = (matters.data ?? []).filter((m) => m.title !== "My documents (quick questions)").length;
  const h = new Date().getHours();
  const hello = h < 12 ? t("start.morning") : h < 17 ? t("start.afternoon") : t("start.evening");

  return (
    <AppShell title={t("nav.home")}>
      <div className="mx-auto max-w-4xl">
        <div className="text-center">
          <p className="vidhi-rise text-sm uppercase tracking-[0.35em] text-[#C8A96B]">{hello}</p>
          <h2 className="vidhi-rise-2 mt-2 text-3xl md:text-4xl" data-testid="start-greeting">
            {t("start.hello", { name: firstName(me?.full_name) })}
          </h2>
        </div>

        <form
          className="glass mt-6 rounded-2xl p-4 md:p-5"
          data-testid="start-ask-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim().length >= 3) navigate(`/ask?q=${encodeURIComponent(q.trim())}`);
          }}
        >
          <label htmlFor="start-q" className="text-sm text-muted-foreground">
            {t("ask.label")}
          </label>
          <Textarea id="start-q" value={q} onChange={(e) => setQ(e.target.value)} rows={2} className="mt-2 text-base" placeholder={t("ask.placeholder")} data-testid="start-ask-input" />
          <div className="mt-3 flex justify-end">
            <Button type="submit" size="lg" disabled={q.trim().length < 3} data-testid="start-ask-submit">
              <Sparkles /> {t("ask.submit")}
            </Button>
          </div>
        </form>

        <div className="mt-6 grid gap-5 md:grid-cols-2">
          <Door
            to="/intelligence"
            icon={Scale}
            accent="#8FA8FF"
            tagTone="blue"
            tag={caseCount ? t("start.d3.count", { n: caseCount }) : t("start.d3.tag")}
            title={t("nav.intelligence")}
            cta={t("start.d3.cta")}
            testId="start-intelligence"
          >
            {t("start.d3.body")}
          </Door>
          <Door
            to="/katalyst"
            icon={Wrench}
            accent="#C8A96B"
            tag={t("start.tk.tag")}
            title={t("start.tk.title")}
            cta={t("start.tk.cta")}
            testId="start-toolkit"
          >
            {t("start.tk.body")}
          </Door>
        </div>

        <p className="mt-6 text-center text-sm" data-testid="start-try">
          <Link to="/katalyst/authority?sample=1" className="inline-block py-2 underline underline-offset-4" data-testid="start-try-authority">
            New here? Try Authority Check on a made-up sample draft →
          </Link>
        </p>

        <section className="mt-8">
          <InlineSearch />
        </section>

        <StartHelp />
      </div>
    </AppShell>
  );
}
