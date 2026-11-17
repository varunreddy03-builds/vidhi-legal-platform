import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useMe } from "@/lib/useMe";

/** Shown until the user proves their own email address - required before emailing anyone else. */
export default function VerifyEmailBanner() {
  const { data: me } = useMe();
  const resend = useMutation({
    mutationFn: () => apiPost<{ ok: boolean }>("/auth/verify-email/request"),
    onSuccess: () => toast.success("Check your inbox for the confirmation link"),
    onError: (e) => toast.error(describe(e)),
  });
  if (!me || me.email_verified) return null;
  return (
    <div
      className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm"
      style={{ borderColor: "#F0A63A66", background: "#F0A63A14" }}
      role="status"
      data-testid="verify-email-banner"
    >
      <span>
        Please confirm your email address ({me.email}) to send notices and statements. We sent you a link.
      </span>
      <Button size="sm" variant="outline" onClick={() => resend.mutate()} disabled={resend.isPending} data-testid="resend-verification">
        {resend.isPending ? "Sending…" : "Send the link again"}
      </Button>
    </div>
  );
}
