import { lazy, Suspense } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Home from "@/pages/Home";
import Login from "@/pages/Login";

/** The tools used to live under /toolkit. Old bookmarks and links forward to /katalyst, keeping the rest of the address. */
function OldToolkitAddress() {
  const { pathname, search } = useLocation();
  return <Navigate to={pathname.replace(/^\/toolkit/, "/katalyst") + search} replace />;
}

// Every screen after the front page loads only when it is opened, so the first page appears quickly even on a slow phone.
const Start = lazy(() => import("@/pages/Start"));
const Toolkit = lazy(() => import("@/pages/Toolkit"));
const Ask = lazy(() => import("@/pages/Ask"));
const Judgments = lazy(() => import("@/pages/Judgments"));
const LegalDirectory = lazy(() => import("@/pages/LegalDirectory"));
const Vault = lazy(() => import("@/pages/Vault"));
const Tax = lazy(() => import("@/pages/Tax"));
const Law = lazy(() => import("@/pages/Law"));
import RecoveryOnly from "@/components/recovery/RecoveryOnly";
const RecoveryGuide = lazy(() => import("@/pages/RecoveryGuide"));
const Intelligence = lazy(() => import("@/pages/Intelligence"));
const AuthorityCheck = lazy(() => import("@/pages/AuthorityCheck"));
const DateList = lazy(() => import("@/pages/DateList"));
const DefectCheck = lazy(() => import("@/pages/DefectCheck"));
const OldCodeCheck = lazy(() => import("@/pages/OldCodeCheck"));
const DeadlineEngine = lazy(() => import("@/pages/DeadlineEngine"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Matters = lazy(() => import("@/pages/Matters"));
const MatterDetail = lazy(() => import("@/pages/MatterDetail"));
const Research = lazy(() => import("@/pages/Research"));
const Drafts = lazy(() => import("@/pages/Drafts"));
const DraftEditor = lazy(() => import("@/pages/DraftEditor"));
const Activity = lazy(() => import("@/pages/Activity"));
const Settings = lazy(() => import("@/pages/Settings"));
const RecoveryDashboard = lazy(() => import("@/pages/RecoveryDashboard"));
const RecoveryCasePage = lazy(() => import("@/components/recovery/RecoveryCaseGate"));
const PaymentSuccess = lazy(() => import("@/pages/PaymentSuccess"));
const PaymentCancel = lazy(() => import("@/pages/PaymentCancel"));
const NotFound = lazy(() => import("@/pages/NotFound"));
const VerifyEmail = lazy(() => import("@/pages/VerifyEmail"));
const Consent = lazy(() => import("@/pages/Consent"));
const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
const AcceptInvite = lazy(() => import("@/pages/AcceptInvite"));
const Privacy = lazy(() => import("@/pages/Privacy"));
const Terms = lazy(() => import("@/pages/Terms"));
const Cookies = lazy(() => import("@/pages/Cookies"));
const DataRights = lazy(() => import("@/pages/DataRights"));
const Support = lazy(() => import("@/pages/Support"));
const Admin = lazy(() => import("@/pages/Admin"));
const Deadlines = lazy(() => import("@/pages/Deadlines"));
const Templates = lazy(() => import("@/pages/Templates"));
const Portal = lazy(() => import("@/pages/Portal"));
const WordTaskPane = lazy(() => import("@/addin/TaskPane")); // the Word add-in panel: loads Office.js only here
const Conflicts = lazy(() => import("@/pages/Conflicts"));
const Clients = lazy(() => import("@/pages/Clients"));
const Lawyers = lazy(() => import("@/pages/Lawyers"));
const Help = lazy(() => import("@/pages/Help"));
const PilotFeedback = lazy(() => import("@/pages/PilotFeedback"));
const Legal = lazy(() => import("@/pages/Legal"));
const LawyerProfile = lazy(() => import("@/pages/Lawyers").then((m) => ({ default: m.LawyerProfile })));

function Loading() {
  return (
    <div className="grid min-h-screen place-items-center" role="status" aria-label="Loading">
      <span className="spinner-ring size-8 text-primary" />
    </div>
  );
}

export default function App() {
  return (
    <>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/addin/word" element={<WordTaskPane />} />
          <Route path="/start" element={<Start />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/intelligence" element={<Intelligence />} />
          <Route path="/toolkit" element={<OldToolkitAddress />} />
          <Route path="/toolkit/*" element={<OldToolkitAddress />} />
          <Route path="/katalyst" element={<Toolkit />} />
          <Route path="/katalyst/authority" element={<AuthorityCheck />} />
          <Route path="/katalyst/authority/:id" element={<AuthorityCheck />} />
          <Route path="/katalyst/dates" element={<DateList />} />
          <Route path="/katalyst/dates/:id" element={<DateList />} />
          <Route path="/katalyst/defects" element={<DefectCheck />} />
          <Route path="/katalyst/defects/:id" element={<DefectCheck />} />
          <Route path="/katalyst/oldcode" element={<OldCodeCheck />} />
          <Route path="/katalyst/oldcode/:id" element={<OldCodeCheck />} />
          <Route path="/katalyst/deadlines" element={<DeadlineEngine />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/matters" element={<Matters />} />
          <Route path="/matters/:matterId" element={<MatterDetail />} />
          <Route path="/research" element={<Research />} />
          <Route path="/drafts" element={<Drafts />} />
          <Route path="/drafts/:draftId" element={<DraftEditor />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/deadlines" element={<Deadlines />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/portal" element={<Portal />} />
          <Route path="/conflicts" element={<Conflicts />} />
          <Route path="/clients" element={<Clients />} />
          <Route path="/lawyers" element={<Lawyers />} />
          <Route path="/help" element={<Help />} />
          <Route path="/feedback" element={<PilotFeedback />} />
          <Route path="/legal" element={<Legal />} />
          <Route path="/lawyers/:id" element={<LawyerProfile />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/law" element={<Law />} />
          <Route path="/judgments" element={<Judgments />} />
          <Route path="/legal-directory" element={<LegalDirectory />} />
          <Route path="/tax" element={<Tax />} />
          <Route path="/vault" element={<Vault />} />
          <Route path="/vault/:id" element={<Vault />} />
          <Route element={<RecoveryOnly />}>
            <Route path="/recovery" element={<RecoveryDashboard />} />
            <Route path="/recovery/guide" element={<RecoveryGuide />} />
            <Route path="/recovery/guide/:caseId" element={<RecoveryGuide />} />
            <Route path="/recovery/cases/:caseId" element={<RecoveryCasePage />} />
          </Route>
          <Route path="/payment/success" element={<PaymentSuccess />} />
          <Route path="/payment/cancel" element={<PaymentCancel />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route element={<RecoveryOnly />}>
            <Route path="/consent/:token" element={<Consent />} />
          </Route>
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/accept-invite" element={<AcceptInvite />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/cookies" element={<Cookies />} />
          <Route path="/data-rights" element={<DataRights />} />
          <Route path="/support" element={<Support />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
      <Toaster richColors />
    </>
  );
}
