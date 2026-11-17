import { useState } from "react";
import { useApiImage } from "@/lib/files";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Status = { enabled: boolean; cap: number; remaining: number };

/** A few simple explanatory pictures a month (Pro). Always labelled AI-generated; never evidence, never real people or documents. */
export default function IllustrationCard() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["images-status"], queryFn: () => apiGet<Status>("/images/status"), retry: false });
  const [prompt, setPrompt] = useState("");
  const [made, setMade] = useState<string | null>(null);
  const imageSrc = useApiImage(made ? `/api/images/${made}` : null);
  const make = useMutation({
    mutationFn: () => apiPost<{ id: string }>("/images/generate", { prompt }),
    onSuccess: async (r) => {
      setMade(r.id);
      await qc.invalidateQueries({ queryKey: ["images-status"] });
    },
    onError: (e) => toast.error(describe(e)),
  });
  const s = status.data;
  if (!s?.enabled) return null;

  return (
    <section className="glass mt-8 rounded-lg p-5" data-testid="illustration-card">
      <h2 className="flex items-center gap-2 font-heading text-sm uppercase tracking-wider text-muted-foreground">
        <ImageIcon className="size-4" /> Simple illustration
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Describe a simple picture that explains something, like the steps of a process. It cannot show real people, documents, signatures or anything that could pass
        as evidence. {s.remaining} of {s.cap} left this month for your organisation.
      </p>
      <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} maxLength={500} className="mt-3" placeholder="For example: three steps from sending a reminder to getting paid" data-testid="illustration-prompt" />
      <Button className="mt-3" size="sm" loading={make.isPending} disabled={prompt.trim().length < 5 || s.remaining < 1} onClick={() => make.mutate()} data-testid="illustration-make">
        Make the illustration
      </Button>
      {made && (
        <figure className="mt-4">
          <img src={imageSrc ?? undefined} alt="AI-generated illustration" className="max-h-80 rounded-md border border-border bg-white" data-testid="illustration-image" />
          <figcaption className="mt-1 text-xs text-muted-foreground">AI-generated illustration. It is not evidence.</figcaption>
        </figure>
      )}
    </section>
  );
}