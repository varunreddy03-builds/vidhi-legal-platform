import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import AuthCard from "@/components/AuthCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

/** Landing page for the emailed reset link. The link works once; every old session is ended on success. */
export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const navigate = useNavigate();

  const reset = useMutation({
    mutationFn: () => apiPost("/auth/reset-password", { token, new_password: password }),
    onSuccess: () => {
      toast.success("Password changed. Please sign in.");
      navigate("/login", { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  if (!token) {
    return (
      <AuthCard title="This link is not complete" testId="reset-password-page">
        <p className="text-sm text-muted-foreground">Open the link from your email again, or ask for a new one.</p>
        <Link to="/forgot-password" className="mt-4 block text-sm underline">
          Ask for a new link
        </Link>
      </AuthCard>
    );
  }

  const mismatch = again.length > 0 && again !== password;
  return (
    <AuthCard title="Choose a new password" subtitle="You will be signed out everywhere else." testId="reset-password-page">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mismatch) reset.mutate();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="pw">New password</Label>
          <Input
            id="pw"
            type="password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            data-testid="reset-password-input"
          />
          <p className="text-xs text-muted-foreground">At least 8 characters; not your email address.</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pw2">Type it again</Label>
          <Input id="pw2" type="password" value={again} onChange={(e) => setAgain(e.target.value)} required />
          {mismatch && <p className="text-xs text-destructive">The two passwords do not match.</p>}
        </div>
        <Button type="submit" className="w-full" disabled={reset.isPending || mismatch} data-testid="reset-submit">
          {reset.isPending ? "Saving…" : "Change password"}
        </Button>
      </form>
    </AuthCard>
  );
}
