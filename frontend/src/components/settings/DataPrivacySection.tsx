import { useState } from "react";
import { fileLinkProps } from "@/lib/files";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import ConfirmDeleteDialog from "@/components/ConfirmDeleteDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { queryClient } from "@/lib/queryClient";
import type { UserOut } from "@/lib/types";

interface Retention {
  retention_days_after_close: number | null;
  notice_days: number;
  min_days: number;
  max_days: number;
  platform_default_days: number;
}

/** Export, retention and erasure. Admin sees export + retention; only the owner sees erasure. */
export default function DataPrivacySection({ me }: { me: UserOut }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const retention = useQuery<Retention>({ queryKey: ["org-retention"], queryFn: () => apiGet<Retention>("/org/retention") });
  const aiSwitch = useQuery<{ enabled: boolean }>({ queryKey: ["org-ai"], queryFn: () => apiGet<{ enabled: boolean }>("/org/ai") });
  const setAi = useMutation({
    mutationFn: (enabled: boolean) => apiPut<{ enabled: boolean }>("/org/ai", { enabled }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["org-ai"] });
      toast.success(r.enabled ? "AI features are on for your organisation" : "AI features are off: nothing from your organisation is sent to an AI service");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const [days, setDays] = useState<string>("");
  const [eraseOpen, setEraseOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [meOpen, setMeOpen] = useState(false);
  const [mePassword, setMePassword] = useState("");
  const eraseMe = useMutation({
    mutationFn: () => apiPost("/privacy/erase-me", { password: mePassword, confirm_email: me.email }),
    onSuccess: () => {
      queryClient.clear();
      toast.success("Your account was erased");
      navigate("/", { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  const chosen = retention.data?.retention_days_after_close ?? null; // null: the platform default applies; 0: keep everything
  const platformDefault = retention.data?.platform_default_days ?? 0;
  const current = chosen === null ? (platformDefault > 0 ? platformDefault : null) : chosen > 0 ? chosen : null; // the period in force, or null for none
  const save = useMutation({
    mutationFn: (value: number | null) => apiPut<Retention>("/org/retention", { retention_days_after_close: value }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["org-retention"] });
      setDays("");
      toast.success(
        r.retention_days_after_close === null
          ? r.platform_default_days > 0
            ? `Back to the default: closed matters are deleted ${r.platform_default_days} days after closing`
            : "Automatic deletion is off"
          : r.retention_days_after_close === 0
            ? "Automatic deletion is off: everything is kept until you delete it"
            : `Closed matters and resolved recoveries will be deleted ${r.retention_days_after_close} days after closing, after ${r.notice_days} days' notice`,
      );
    },
    onError: (e) => toast.error(describe(e)),
  });
  const erase = useMutation({
    mutationFn: () => apiDelete("/org", { password, organization_name: me.organization_name }),
    onSuccess: () => {
      queryClient.clear();
      toast.success("Your organisation and all its data were deleted");
      navigate("/", { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <section className="glass rounded-lg p-5" data-testid="settings-data">
      <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">Data &amp; privacy</h2>
      <p className="mt-2 text-xs text-muted-foreground">
        How your data is handled is described in{" "}
        <Link to="/privacy" className="underline">
          the privacy notice
        </Link>
        .
      </p>

      <div className="mt-4">
        <p className="text-sm">Download everything</p>
        <p className="text-xs text-muted-foreground">One file with every record and the original documents, for you to keep or move.</p>
        <a {...fileLinkProps("/api/org/export")}>
          <Button size="sm" variant="outline" className="mt-2" data-testid="export-download">
            Download export
          </Button>
        </a>
      </div>

      <div className="mt-5 border-t border-border pt-4" data-testid="ai-switch">
        <p className="text-sm">AI features</p>
        <p className="text-xs text-muted-foreground">
          {aiSwitch.data?.enabled === false
            ? "Off. Nothing from your organisation is sent to an AI, scan-reading, voice or picture service. Tools that do not use AI keep working."
            : "On. Questions and the text of documents you ask about are sent to AI services to write answers. Switch off if your clients' terms do not allow that."}
        </p>
        <Button
          size="sm"
          variant="outline"
          className="mt-2"
          disabled={aiSwitch.isLoading || setAi.isPending}
          onClick={() => setAi.mutate(aiSwitch.data?.enabled === false)}
          data-testid="ai-switch-toggle"
        >
          {aiSwitch.data?.enabled === false ? "Turn AI on" : "Turn AI off"}
        </Button>
      </div>

      <div className="mt-5 border-t border-border pt-4">
        <p className="text-sm">Automatic clean-up</p>
        <p className="text-xs text-muted-foreground">
          {current === null
            ? "Off. Nothing is ever deleted unless you delete it."
            : `On: closed matters and resolved recoveries are deleted ${current} days after closing. Owners are emailed ${retention.data?.notice_days ?? 30} days before anything is deleted; re-opening an item or placing a matter under legal hold stops it.`}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Input
            type="number"
            min={retention.data?.min_days ?? 30}
            max={retention.data?.max_days ?? 3650}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            placeholder={`days (${retention.data?.min_days ?? 30}–${retention.data?.max_days ?? 3650})`}
            className="w-44"
            data-testid="retention-days"
          />
          <Button size="sm" variant="outline" disabled={!days || save.isPending} onClick={() => save.mutate(Number(days))} data-testid="retention-save">
            Turn on
          </Button>
          {current !== null && (
            <Button size="sm" variant="ghost" disabled={save.isPending} onClick={() => save.mutate(0)} data-testid="retention-off">
              Turn off
            </Button>
          )}
          {chosen !== null && platformDefault > 0 && (
            <Button size="sm" variant="ghost" disabled={save.isPending} onClick={() => save.mutate(null)} data-testid="retention-default">
              Use the default ({platformDefault} days)
            </Button>
          )}
        </div>
      </div>

      <div className="mt-5 border-t border-border pt-4" data-testid="erase-me-block">
        <p className="text-sm">Erase my account</p>
        <p className="text-xs text-muted-foreground">
          Deletes your sign-in, devices, messages to support and your name and email in the activity log. The records you made for the firm stay with the firm. If you are the only owner, make
          someone else an owner first.
        </p>
        <Button size="sm" variant="destructive" className="mt-2" onClick={() => setMeOpen(true)} data-testid="erase-me">
          Erase my account…
        </Button>
        <ConfirmDeleteDialog
          open={meOpen}
          onOpenChange={(o) => {
            setMeOpen(o);
            if (!o) setMePassword("");
          }}
          title="Erase your account?"
          description="Your account is deleted at once and nobody can get it back. Copies inside encrypted backups expire within 30 days."
          confirmWord={me.email}
          confirmLabel="Erase my account"
          pending={eraseMe.isPending}
          canConfirm={mePassword.length > 0}
          onConfirm={() => eraseMe.mutate()}
          extra={
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Your password</label>
              <Input type="password" value={mePassword} onChange={(e) => setMePassword(e.target.value)} data-testid="erase-me-password" />
            </div>
          }
        />
      </div>

      {me.role === "OWNER" && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="text-sm">Erase this organisation</p>
          <p className="text-xs text-muted-foreground">
            Permanently deletes every matter, document, case, member and record. Download an export first. This cannot be undone.
          </p>
          <Button size="sm" variant="destructive" className="mt-2" onClick={() => setEraseOpen(true)} data-testid="erase-org">
            Erase organisation…
          </Button>
          <ConfirmDeleteDialog
            open={eraseOpen}
            onOpenChange={(o) => {
              setEraseOpen(o);
              if (!o) setPassword("");
            }}
            title="Erase the whole organisation?"
            description="Everything is deleted at once and nobody can get it back. Copies inside encrypted backups expire within 30 days."
            confirmWord={me.organization_name}
            confirmLabel="Erase everything"
            pending={erase.isPending}
            canConfirm={password.length > 0}
            onConfirm={() => erase.mutate()}
            extra={
              <div className="space-y-1.5">
                <label className="text-xs text-muted-foreground">Your password</label>
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} data-testid="erase-password" />
              </div>
            }
          />
        </div>
      )}
    </section>
  );
}
