import { Navigate, Outlet } from "react-router-dom";
import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";

/** Route wrapper: the Legal Recovery pages exist only while the installation has Legal Recovery switched on (backend RECOVERY_ENABLED). Otherwise the address goes to the start page.
 * While the answer is loading nothing is shown, so a Recovery page never flashes up and disappears. */
export default function RecoveryOnly() {
  const { enabled, ready } = useRecoveryEnabled();
  if (!ready) return null;
  return enabled ? <Outlet /> : <Navigate to="/" replace />;
}
