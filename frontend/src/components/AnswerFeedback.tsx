import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { apiGet } from "@/lib/api";
import { apiPut } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useT } from "@/lib/i18n/I18nProvider";

type Vote = { rating: "up" | "down" | null; comment: string };

/** Thumbs up or down on one answer. A thumbs-down offers a short note about what was wrong. Private to your organisation. */
export default function AnswerFeedback({ answerId }: { answerId: string }) {
  const t = useT();
  const q = useQuery({ queryKey: ["feedback", answerId], queryFn: () => apiGet<Vote>(`/research/${answerId}/feedback`), retry: false });
  const [note, setNote] = useState("");
  const [asking, setAsking] = useState(false);
  const save = useMutation({
    mutationFn: (v: { rating: "up" | "down"; comment?: string }) => apiPut<Vote>(`/research/${answerId}/feedback`, v),
    onSuccess: (v) => {
      q.refetch();
      setAsking(false);
      toast.success(v.rating === "up" ? t("fb.thanks") : t("fb.thanks.down"));
    },
    onError: (e) => toast.error(describe(e)),
  });
  const rating = q.data?.rating ?? null;
  const btn = (active: boolean) => `rounded-full border p-2 transition-colors ${active ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground"}`;

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="answer-feedback">
      <span className="text-xs text-muted-foreground">{t("fb.question")}</span>
      <button className={btn(rating === "up")} aria-label={t("fb.up")} aria-pressed={rating === "up"} onClick={() => save.mutate({ rating: "up" })} data-testid="feedback-up">
        <ThumbsUp className="size-4" />
      </button>
      <button className={btn(rating === "down")} aria-label={t("fb.down")} aria-pressed={rating === "down"} onClick={() => setAsking(true)} data-testid="feedback-down">
        <ThumbsDown className="size-4" />
      </button>
      {asking && (
        <form
          className="flex w-full flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ rating: "down", comment: note });
          }}
        >
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder={t("fb.note")} className="h-9 min-w-48 flex-1 rounded-md border border-border bg-background px-3 text-sm" data-testid="feedback-note" />
          <button type="submit" className="rounded-md border border-border px-3 py-1.5 text-sm" data-testid="feedback-send">
            {t("fb.send")}
          </button>
        </form>
      )}
    </div>
  );
}