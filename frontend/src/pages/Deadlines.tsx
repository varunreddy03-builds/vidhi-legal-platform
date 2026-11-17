import { useEffect, useState } from "react";
import { fileLinkProps } from "@/lib/files";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { canInstall, disablePush, enablePush, install, isSubscribed, needsIosInstallSteps, onInstallChange, pushSupported } from "@/lib/push";
import type { Matter } from "@/lib/types";

interface DateItem {
  id: string;
  title: string;
  kind: string;
  notes: string;
  status: "OPEN" | "DONE";
  starts_at: string;
  starts_local: string;
  tz: string;
  matter_id: string | null;
  matter_title: string | null;
  reminders: number[];
  reminders_sent: number[];
  channels: { email: boolean; push: boolean; sms: boolean };
}
interface DateList {
  items: DateItem[];
  time_zone_default: string;
  reminder_choices: number[];
  kinds: string[];
  notice: string;
}

const ZONES = ["Asia/Kolkata", "Asia/Dubai", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Singapore"];
const REMINDER_LABEL: Record<number, string> = { 10080: "1 week before", 4320: "3 days before", 1440: "1 day before", 120: "2 hours before", 60: "1 hour before", 15: "15 minutes before" };
const KIND_LABEL: Record<string, string> = { hearing: "Hearing", deadline: "Deadline", filing: "Filing", meeting: "Meeting", other: "Other" };

/** The wall-clock time exactly as saved (in its own time zone), e.g. "05 Nov 2026, 10:30". */
const show = (local: string) => new Date(local).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

function Toggle({ label, checked, onChange, disabled, hint, testId }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; hint?: string; testId?: string }) {
  return (
    <label className={`flex items-start gap-2 text-sm ${disabled ? "opacity-60" : ""}`}>
      <input type="checkbox" className="mt-1" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} data-testid={testId} />
      <span>
        {label}
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
    </label>
  );
}

function DeviceControls() {
  const config = useQuery({ queryKey: ["push-config"], queryFn: () => apiGet<{ available: boolean; public_key: string | null }>("/push/config"), retry: false });
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [installable, setInstallable] = useState(canInstall());
  useEffect(() => {
    void isSubscribed().then(setOn);
    return onInstallChange(() => setInstallable(canInstall()));
  }, []);
  const toggle = async () => {
    setBusy(true);
    try {
      if (on) await disablePush();
      else if (config.data?.public_key) await enablePush(config.data.public_key);
      setOn(await isSubscribed());
      toast.success(on ? "Notifications are off on this device." : "Notifications are on for this device.");
    } catch (e) {
      toast.error(describe(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="device-controls">
      {pushSupported() && config.data?.available && (
        <Button size="sm" variant="outline" loading={busy} onClick={() => void toggle()} data-testid="push-toggle" className="h-auto min-h-7 max-w-full whitespace-normal text-left">
          {on ? "Turn off notifications on this device" : "Turn on notifications on this device"}
        </Button>
      )}
      {!installable && needsIosInstallSteps() && (
        <p className="text-xs text-muted-foreground" data-testid="ios-install-steps">
          To install VIDHI on an iPhone or iPad: open this page in Safari, tap the Share button, then “Add to Home Screen”.
        </p>
      )}
      {installable && (
        <Button size="sm" variant="outline" onClick={() => void install()} data-testid="install-app" className="h-auto min-h-7 max-w-full whitespace-normal text-left">
          Install the app
        </Button>
      )}
    </div>
  );
}

export default function Deadlines() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["deadlines"], queryFn: () => apiGet<DateList>("/deadlines") });
  const matters = useQuery({ queryKey: ["matters"], queryFn: () => apiGet<Matter[]>("/matters"), retry: false });
  const phone = useQuery({ queryKey: ["phone"], queryFn: () => apiGet<{ verified: boolean; alerts: boolean }>("/auth/phone"), retry: false });
  const textReady = !!(phone.data?.verified && phone.data?.alerts);
    // Some browsers still report the old name for India's zone; use the current one so it matches the list.
  const guess = { "Asia/Calcutta": "Asia/Kolkata" }[Intl.DateTimeFormat().resolvedOptions().timeZone] ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = ZONES.includes(guess) ? ZONES : [guess, ...ZONES];

  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("hearing");
  const [when, setWhen] = useState("");
  const [tz, setTz] = useState(ZONES.includes(guess) ? guess : "Asia/Kolkata");
  const [matterId, setMatterId] = useState("");
  const [notes, setNotes] = useState("");
  const [reminders, setReminders] = useState<number[]>([1440, 60]);
  const [email, setEmail] = useState(true);
  const [push, setPush] = useState(true);
  const [sms, setSms] = useState(false);

  const refresh = () => qc.invalidateQueries({ queryKey: ["deadlines"] });
  const add = useMutation({
    mutationFn: () => apiPost("/deadlines", { title, kind, starts_local: when, tz, matter_id: matterId || null, notes, reminders, channels: { email, push, sms: sms && textReady } }),
    onSuccess: () => {
      setTitle("");
      setNotes("");
      setWhen("");
      toast.success("Date saved.");
      void refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const change = useMutation({
    mutationFn: (v: { id: string; status: "OPEN" | "DONE" }) => apiPatch(`/deadlines/${v.id}`, { status: v.status }),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(describe(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/deadlines/${id}`),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(describe(e)),
  });
  const toggleReminder = (m: number, on: boolean) => setReminders((cur) => (on ? [...cur, m].sort((a, b) => b - a) : cur.filter((x) => x !== m)));

  return (
    <AppShell title="Dates and hearings">
      <div className="mx-auto max-w-4xl space-y-6" data-testid="deadlines-page">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-2xl">Dates and hearings</h2>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{list.data?.notice ?? "Dates you save here come with reminders. They are entered by you and are not checked against any court record."}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <a {...fileLinkProps("/api/deadlines/calendar.ics", { download: false })} className="inline-block py-1.5 text-sm underline underline-offset-4" data-testid="calendar-all">
              Add all to my calendar (.ics)
            </a>
          </div>
        </div>
        <DeviceControls />

        <form
          className="glass space-y-4 rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
          data-testid="deadline-form"
        >
          <h3 className="text-lg">Save a date</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="d-title">What is it?</Label>
              <Input id="d-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required placeholder="e.g. Hearing, written statement due" data-testid="deadline-title" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="d-kind">Kind</Label>
              <select id="d-kind" value={kind} onChange={(e) => setKind(e.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm">
                {(list.data?.kinds ?? Object.keys(KIND_LABEL)).map((k) => (
                  <option key={k} value={k}>{KIND_LABEL[k] ?? k}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="d-when">Date and time</Label>
              <Input id="d-when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required data-testid="deadline-when" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="d-tz">Time zone of that time</Label>
              <select id="d-tz" value={tz} onChange={(e) => setTz(e.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm">
                {zones.map((z) => (
                  <option key={z} value={z}>{z}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="d-matter">Matter (optional)</Label>
              <select id="d-matter" value={matterId} onChange={(e) => setMatterId(e.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm">
                <option value="">None</option>
                {(matters.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>{m.title}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="d-notes">Notes (optional)</Label>
              <Textarea id="d-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} maxLength={1000} />
            </div>
          </div>
          <fieldset className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <legend className="text-sm font-medium">Remind me</legend>
              {(list.data?.reminder_choices ?? [1440, 60]).map((m) => (
                <Toggle key={m} label={REMINDER_LABEL[m] ?? `${m} minutes before`} checked={reminders.includes(m)} onChange={(on) => toggleReminder(m, on)} testId={`remind-${m}`} />
              ))}
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium">How</p>
              <Toggle label="Email" checked={email} onChange={setEmail} />
              <Toggle label="Notification on my devices" checked={push} onChange={setPush} hint="Turn notifications on for each device above." />
              <Toggle
                label="Text message"
                checked={sms && textReady}
                onChange={setSms}
                disabled={!textReady}
                hint={textReady ? "Sent to your verified phone. It never contains names or details." : "Add and verify your phone in Settings and switch alerts on first."}
              />
            </div>
          </fieldset>
          <Button type="submit" loading={add.isPending} data-testid="deadline-save">Save date</Button>
        </form>

        <div className="space-y-3" data-testid="deadline-list">
          {list.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {!list.isLoading && (list.data?.items ?? []).length === 0 && <p className="text-sm text-muted-foreground" data-testid="deadline-empty">No dates saved yet.</p>}
          {(list.data?.items ?? []).map((d) => (
            <div key={d.id} className={`glass rounded-lg p-4 ${d.status === "DONE" ? "opacity-60" : ""}`} data-testid="deadline-row">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{d.title}</p>
                  <p className="text-sm text-muted-foreground">
                    {KIND_LABEL[d.kind] ?? d.kind} · {show(d.starts_local)} ({d.tz})
                    {d.matter_id && (
                      <>
                        {" "}· <Link to={`/matters/${d.matter_id}`} className="underline underline-offset-4">{d.matter_title ?? "Matter"}</Link>
                      </>
                    )}
                  </p>
                  {d.notes && <p className="mt-1 text-sm">{d.notes}</p>}
                  <p className="mt-1 text-xs text-muted-foreground">
                    Reminders: {d.reminders.length ? d.reminders.map((m) => REMINDER_LABEL[m] ?? `${m} min`).join(", ") : "none"}
                    {d.reminders_sent.length > 0 && ` · sent: ${d.reminders_sent.map((m) => REMINDER_LABEL[m] ?? m).join(", ")}`}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <a {...fileLinkProps(`/api/deadlines/${d.id}/calendar.ics`, { download: false })} className="text-sm underline underline-offset-4">Calendar</a>
                  <Button size="xs" variant="outline" onClick={() => change.mutate({ id: d.id, status: d.status === "OPEN" ? "DONE" : "OPEN" })}>
                    {d.status === "OPEN" ? "Mark done" : "Reopen"}
                  </Button>
                  <Button size="xs" variant="destructive" onClick={() => remove.mutate(d.id)} data-testid="deadline-delete">Delete</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}