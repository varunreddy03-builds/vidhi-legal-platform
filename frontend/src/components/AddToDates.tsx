import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

const DATE_KINDS = ["hearing", "deadline", "filing", "meeting", "other"];

type Props = {
  /** first words of the title the user sees (they may change it) */
  title: string;
  /** YYYY-MM-DD, shown in the date box (the user may change it) */
  date: string;
  /** goes into the notes of the new date, so it is clear where it came from */
  note: string;
  /** the line above the form, for example what to check the date against */
  hint: string;
  kind?: string;
  /** test ids are `${testPrefix}-add-open`, `-add-form`, `-add-title`, `-add-date`, `-add-time`, `-add-kind`, `-add-submit` and `${testPrefix}-added` */
  testPrefix: string;
};

/** Lets the user copy one date into their own Dates (with reminders). Nothing is added until they press Add, and the date and the title are theirs to change. */
export default function AddToDates({ title: initialTitle, date: initialDate, note, hint, kind: initialKind = "hearing", testPrefix }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(initialTitle.slice(0, 120));
  const [date, setDate] = useState(initialDate);
  const [time, setTime] = useState("10:00");
  const [kind, setKind] = useState(initialKind);
  const [added, setAdded] = useState(false);
  const add = useMutation({
    mutationFn: () => apiPost("/deadlines", { title: title.trim(), kind, starts_local: `${date}T${time}`, notes: note.slice(0, 1000) }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["deadlines"] });
      setAdded(true);
      setOpen(false);
    },
    onError: (e) => toast.error(describe(e)),
  });
  if (added) {
    return (
      <p className="mt-2 text-xs" data-testid={`${testPrefix}-added`}>
        Added to your Dates. <Link to="/deadlines" className="underline">Open Dates</Link>
      </p>
    );
  }
  if (!open) {
    return (
      <Button size="sm" variant="outline" className="mt-2" onClick={() => setOpen(true)} data-testid={`${testPrefix}-add-open`}>
        Add to my Dates
      </Button>
    );
  }
  return (
    <form
      className="mt-2 space-y-2 rounded-lg border border-border p-3"
      data-testid={`${testPrefix}-add-form`}
      onSubmit={(e) => {
        e.preventDefault();
        if (date && title.trim()) add.mutate();
      }}
    >
      <p className="text-xs text-muted-foreground">{hint}</p>
      <Input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} aria-label="Title" data-testid={`${testPrefix}-add-title`} />
      <div className="flex flex-wrap gap-2">
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" className="w-40" data-testid={`${testPrefix}-add-date`} />
        <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} aria-label="Time" className="w-28" data-testid={`${testPrefix}-add-time`} />
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind" className="rounded-md border border-border bg-background px-2 text-sm" data-testid={`${testPrefix}-add-kind`}>
          {DATE_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>
      <div className="flex gap-2">
        <Button size="sm" type="submit" disabled={add.isPending || !date || !title.trim()} data-testid={`${testPrefix}-add-submit`}>
          {add.isPending ? "Adding…" : "Add"}
        </Button>
        <Button size="sm" type="button" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
