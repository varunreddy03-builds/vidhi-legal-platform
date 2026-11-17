import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import AuthCard from "@/components/AuthCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const send = useMutation({
    mutationFn: () => apiPost<{ ok: boolean; message: string }>("/auth/forgot-password", { email }),
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <AuthCard
      title="Forgot your password?"
      subtitle="Enter your email address and we will send you a link to choose a new one."
      testId="forgot-password-page"
    >
      {send.isSuccess ? (
        <p className="text-sm" data-testid="forgot-password-sent">
          {send.data.message} The link works once and expires in an hour.
        </p>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            send.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              data-testid="forgot-email-input"
            />
          </div>
          <Button type="submit" className="w-full" disabled={send.isPending} data-testid="forgot-submit">
            {send.isPending ? "Sending…" : "Send reset link"}
          </Button>
        </form>
      )}
      <Link to="/login" className="mt-4 block text-center text-xs text-muted-foreground hover:text-foreground">
        Back to sign in
      </Link>
    </AuthCard>
  );
}
