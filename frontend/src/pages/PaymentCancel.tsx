import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import { Link } from "react-router-dom";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { buttonVariants } from "@/components/ui/button";

export default function PaymentCancel() {
  const { enabled: recoveryOn } = useRecoveryEnabled();
  return (
    <div className="relative flex min-h-screen items-center justify-center px-4">
      <NervousSystemBackground intensity="ambient" />
      <div className="glass relative z-10 w-full max-w-md rounded-xl p-8 text-center" data-testid="payment-cancel">
        <h1 className="text-2xl">Payment cancelled</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          No charge was made. You can upgrade any time.{recoveryOn ? " Legal Recovery stays free regardless." : ""}
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <Link to="/settings" className={buttonVariants({})}>
            Back to settings
          </Link>
          {recoveryOn && (
            <Link to="/recovery" className={buttonVariants({ variant: "outline" })}>
              Use free Recovery
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
