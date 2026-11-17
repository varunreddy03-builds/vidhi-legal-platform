import { lazy } from "react";
import { Navigate, useParams } from "react-router-dom";
import { useRecoveryMode } from "@/lib/recovery/useRecoveryMode";

const RecoveryCasePage = lazy(() => import("@/pages/RecoveryCase"));

/** The full case page (payments, statements, delivery, next steps) belongs to the full flow. With the switch off, its address opens the guide for the same claim instead. */
export default function RecoveryCaseGate() {
  const { caseId } = useParams();
  const { full, ready } = useRecoveryMode();
  if (!ready) return null;
  return full ? <RecoveryCasePage /> : <Navigate to={`/recovery/guide/${caseId}`} replace />;
}
