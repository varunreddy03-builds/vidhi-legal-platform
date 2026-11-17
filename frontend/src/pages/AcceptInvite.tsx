import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import AuthCard from "@/components/AuthCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiGet, apiPost } from "@/lib/api";
import { beginSession } from "@/lib/session";
import { describe } from "@/lib/interaction";
import type { UserOut } from "@/lib/types";

interface InviteInfo {
  organization_name: string;
  email: string;
  role: string;
  invited_by_name: string;
}

/** Landing page for an emailed team invitation: shows who invited you, you choose a name and password. */
export default function AcceptInvite() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [privacy, setPrivacy] = useState(false);

  const info = useQuery<InviteInfo>({
    queryKey: ["invite", token],
    queryFn: () => apiGet<InviteInfo>(`/auth/invites/${encodeURIComponent(token)}`),
    enabled: !!token,
    retry: false,
  });

  const accept = useMutation({
    mutationFn: () =>
      apiPost<UserOut>("/auth/accept-invite", { token, full_name: fullName, password, accept_privacy: privacy }),
    onSuccess: async (u) => {
      await beginSession();
      toast.success(`Welcome to ${u.organization_name}`);
      navigate(u.role === "CLIENT" ? "/portal" : "/dashboard", { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  if (!token || info.isError) {
    return (
      <AuthCard title="This invitation is not valid any more" testId="accept-invite-page">
        <p className="text-sm text-muted-foreground">
          It may have expired, been used already, or been cancelled. Ask the person who invited you to send a new one.
        </p>
        <Link to="/login" className="mt-4 block text-sm underline">
          Go to sign in
        </Link>
      </AuthCard>
    );
  }
  if (!info.data) {
    return (
      <AuthCard title="Checking your invitation…" testId="accept-invite-page">
        <p className="text-sm text-muted-foreground">One moment.</p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={info.data.role === "CLIENT" ? `Your client portal at ${info.data.organization_name}` : `Join ${info.data.organization_name}`}
      subtitle={
        info.data.role === "CLIENT"
          ? `${info.data.invited_by_name || "Your lawyer"} invited ${info.data.email} to a private portal where they can share updates and documents with you.`
          : `${info.data.invited_by_name || "A colleague"} invited ${info.data.email} as ${info.data.role.toLowerCase()}.`
      }
      testId="accept-invite-page"
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          accept.mutate();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="name">Your full name</Label>
          <Input id="name" value={fullName} onChange={(e) => setFullName(e.target.value)} required data-testid="invite-name-input" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pw">Choose a password</Label>
          <Input
            id="pw"
            type="password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            data-testid="invite-password-input"
          />
          <p className="text-xs text-muted-foreground">At least 8 characters; not your email address.</p>
        </div>
        <label className="flex items-start gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={privacy}
            onChange={(e) => setPrivacy(e.target.checked)}
            className="mt-0.5"
            data-testid="invite-privacy-checkbox"
          />
          <span>
            I have read{" "}
            <Link to="/privacy" target="_blank" className="underline">
              how VIDHI handles data
            </Link>
            .
          </span>
        </label>
        <Button type="submit" className="w-full" disabled={accept.isPending || !privacy} data-testid="invite-submit">
          {accept.isPending ? "Joining…" : info.data.role === "CLIENT" ? "Open my portal" : "Join the team"}
        </Button>
      </form>
    </AuthCard>
  );
}
