import React from "react";
import "./App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import RequestAppointment from "./pages/RequestAppointment";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import PortalIndex from "./pages/PortalIndex";
import PatientDashboard from "./pages/patient/PatientDashboard";
import PatientIntake from "./pages/patient/PatientIntake";
import PatientChart from "./pages/patient/PatientChart";
import PatientFiles from "./pages/patient/PatientFiles";
import PatientAppointments from "./pages/patient/PatientAppointments";
import PatientBilling from "./pages/patient/PatientBilling";
import PatientPlan from "./pages/patient/PatientPlan";
import PatientSymptoms from "./pages/patient/PatientSymptoms";
import PatientLabs from "./pages/patient/PatientLabs";
import Security from "./pages/portal/Security";
import Messages from "./pages/portal/Messages";
import ProviderDashboard from "./pages/provider/ProviderDashboard";
import PatientsList from "./pages/provider/PatientsList";
import ProviderPatientChart from "./pages/provider/PatientChart";
import ProviderSchedule from "./pages/provider/ProviderSchedule";
import Availability from "./pages/provider/Availability";
import AdminOverview from "./pages/admin/AdminOverview";
import AdminUsers from "./pages/admin/AdminUsers";
import AdminAudit from "./pages/admin/AdminAudit";
import AdminSessionExplorer from "./pages/admin/AdminSessionExplorer";
import AdminReminders from "./pages/admin/AdminReminders";
import AdminNotesList from "./pages/admin/AdminNotesList";
import AdminFilesList from "./pages/admin/AdminFilesList";
import AdminFormsConsents from "./pages/admin/AdminFormsConsents";
import FormResponder from "./pages/FormResponder";
import SoapNotes from "./pages/portal/SoapNotes";
import Protocols from "./pages/portal/Protocols";
import PatientProtocols from "./pages/patient/PatientProtocols";
import DocumentLibrary from "./pages/admin/DocumentLibrary";
import PushOptInBanner from "./components/PushOptInBanner";
import SessionTimeout from "./components/SessionTimeout";
import AdminCompliance from "./pages/admin/AdminCompliance";
import TelehealthVisit from "./pages/TelehealthVisit";
import MyAccount from "./pages/portal/MyAccount";
import FrontDesk from "./pages/portal/FrontDesk";
import PointOfSale from "./pages/portal/PointOfSale";
import Treatments from "./pages/portal/Treatments";
import TimeClock from "./pages/portal/TimeClock";
import Inventory from "./pages/portal/Inventory";
import Transactions from "./pages/portal/Transactions";
import ImportClients from "./pages/portal/ImportClients";
import Analytics from "./pages/portal/Analytics";
import AppointmentsEHR from "./pages/provider/AppointmentsEHR";
import TelehealthHub from "./pages/portal/TelehealthHub";
import Tasks from "./pages/portal/Tasks";
import LabReviewQueue from "./pages/portal/LabReviewQueue";
import CampaignCenter from "./pages/portal/CampaignCenter";
import Accounting from "./pages/portal/Accounting";
import StaffLogin from "./pages/StaffLogin";
import MfaChallenge from "./pages/MfaChallenge";
import ChangePassword from "./pages/ChangePassword";
import ResetPassword from "./pages/ResetPassword";
import Unsubscribe from "./pages/Unsubscribe";
import LegalHub from "./pages/LegalHub";
import LegalPolicyPage from "./pages/LegalPolicyPage";
import ReacceptancePolicyGate from "./components/ReacceptancePolicyGate";
import StaffDashboard from "./pages/staff/StaffDashboard";
import { Toaster } from "./components/ui/toaster";
import { AuthProvider } from "./lib/auth";
import { Protected } from "./lib/Protected";
import ErrorBoundary from "./components/ErrorBoundary";

// Consolidated role sets so route access stays in sync across the app.
// Front-desk aliases (`front_desk`, `frontdesk`) are both accepted because
// legacy user records use the hyphen-free form.
const FRONT_DESK_ROLES = ["admin", "staff", "front_desk", "frontdesk"];
const CLINICAL_STAFF_ROLES = ["admin", "practitioner", "staff", "medical_assistant", "front_desk", "frontdesk"];
const PROVIDER_ROLES = ["admin", "practitioner", "staff", "medical_assistant", "front_desk", "frontdesk"];
const READ_ONLY_WORKFORCE = [...FRONT_DESK_ROLES, "practitioner", "medical_assistant", "auditor"];

function App() {
  return (
    <div className="App">
      <ErrorBoundary>
        <BrowserRouter>
          <AuthProvider>
          <PushOptInBanner />
          <SessionTimeout />
          <ReacceptancePolicyGate />
          {/* Shared role sets are defined at module scope above. */}
          <Routes>
            {/* Public marketing */}
            <Route path="/" element={<Home />} />
            <Route path="/request-appointment" element={<RequestAppointment />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/login" element={<Login />} />
            <Route path="/patient-login" element={<Login />} />
            <Route path="/staff-login" element={<StaffLogin />} />
            <Route path="/mfa-challenge" element={<MfaChallenge />} />
            <Route path="/change-password" element={<Protected><ChangePassword /></Protected>} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/unsubscribe" element={<Unsubscribe />} />
            {/* Legal & Policies (publicly readable) */}
            <Route path="/legal" element={<LegalHub />} />
            <Route path="/legal/:slug" element={<LegalPolicyPage />} />

            {/* Portal redirect */}
            <Route path="/portal" element={<PortalIndex />} />

            {/* Telehealth */}
            <Route path="/portal/visit/:id" element={
              <Protected roles={["client", "practitioner", "staff", "admin", "medical_assistant"]}><TelehealthVisit /></Protected>
            } />
            <Route path="/portal/patient/telehealth" element={<Protected roles={["client"]}><TelehealthHub /></Protected>} />
            <Route path="/portal/provider/telehealth" element={<Protected roles={["practitioner", "admin"]}><TelehealthHub /></Protected>} />
            <Route path="/portal/staff/telehealth" element={<Protected roles={FRONT_DESK_ROLES}><TelehealthHub /></Protected>} />
            <Route path="/portal/staff/tasks" element={<Protected roles={CLINICAL_STAFF_ROLES}><Tasks /></Protected>} />
            <Route path="/portal/staff/lab-review" element={<Protected roles={CLINICAL_STAFF_ROLES}><LabReviewQueue /></Protected>} />
            <Route path="/portal/staff/campaigns" element={<Protected roles={["staff", "admin", "practitioner", "front_desk", "frontdesk"]}><CampaignCenter /></Protected>} />
            <Route path="/portal/admin/accounting" element={<Protected roles={["admin", "auditor"]}><Accounting /></Protected>} />
            <Route path="/portal/admin/telehealth" element={<Protected roles={["admin"]}><TelehealthHub /></Protected>} />

            {/* Staff portal (front-desk-first) */}
            <Route path="/portal/staff" element={<Protected roles={FRONT_DESK_ROLES}><StaffDashboard /></Protected>} />
            <Route path="/portal/staff/front-desk" element={<Protected roles={FRONT_DESK_ROLES}><FrontDesk /></Protected>} />
            <Route path="/portal/staff/appointments" element={<Protected roles={FRONT_DESK_ROLES}><AppointmentsEHR /></Protected>} />
            <Route path="/portal/staff/patients" element={<Protected roles={READ_ONLY_WORKFORCE}><PatientsList /></Protected>} />
            <Route path="/portal/staff/pos" element={<Protected roles={FRONT_DESK_ROLES}><PointOfSale /></Protected>} />
            <Route path="/portal/staff/transactions" element={<Protected roles={[...FRONT_DESK_ROLES, "auditor"]}><Transactions /></Protected>} />
            <Route path="/portal/staff/inventory" element={<Protected roles={FRONT_DESK_ROLES}><Inventory /></Protected>} />
            <Route path="/portal/staff/treatments" element={<Protected roles={[...FRONT_DESK_ROLES, "practitioner"]}><Treatments /></Protected>} />
            <Route path="/portal/staff/time-clock" element={<Protected roles={CLINICAL_STAFF_ROLES}><TimeClock /></Protected>} />
            <Route path="/portal/staff/account" element={<Protected roles={CLINICAL_STAFF_ROLES}><MyAccount /></Protected>} />
            <Route path="/portal/staff/security" element={<Protected roles={CLINICAL_STAFF_ROLES}><Security /></Protected>} />

            {/* Patient */}
            <Route path="/portal/patient" element={<Protected roles={["client"]}><PatientDashboard /></Protected>} />
            <Route path="/portal/patient/intake" element={<Protected roles={["client"]}><PatientIntake /></Protected>} />
            <Route path="/portal/patient/chart" element={<Protected roles={["client"]}><PatientChart /></Protected>} />
            <Route path="/portal/patient/files" element={<Protected roles={["client"]}><PatientFiles /></Protected>} />
            <Route path="/portal/patient/appointments" element={<Protected roles={["client"]}><PatientAppointments /></Protected>} />
            <Route path="/portal/patient/billing" element={<Protected roles={["client"]}><PatientBilling /></Protected>} />
            <Route path="/portal/patient/plan" element={<Protected roles={["client"]}><PatientPlan /></Protected>} />
            <Route path="/portal/patient/symptoms" element={<Protected roles={["client"]}><PatientSymptoms /></Protected>} />
            <Route path="/portal/patient/labs" element={<Protected roles={["client"]}><PatientLabs /></Protected>} />
            <Route path="/portal/patient/messages" element={<Protected roles={["client"]}><Messages /></Protected>} />
            <Route path="/portal/patient/account" element={<Protected roles={["client"]}><MyAccount /></Protected>} />
            <Route path="/portal/patient/security" element={<Protected roles={["client"]}><Security /></Protected>} />

            {/* Provider & staff */}
            <Route path="/portal/provider" element={<Protected roles={PROVIDER_ROLES}><ProviderDashboard /></Protected>} />
            <Route path="/portal/provider/patients" element={<Protected roles={READ_ONLY_WORKFORCE}><PatientsList /></Protected>} />
            <Route path="/portal/provider/patients/:id" element={<Protected roles={READ_ONLY_WORKFORCE}><ProviderPatientChart /></Protected>} />
            <Route path="/portal/provider/schedule" element={<Protected roles={PROVIDER_ROLES}><AppointmentsEHR /></Protected>} />
            <Route path="/portal/provider/appointments" element={<Protected roles={PROVIDER_ROLES}><AppointmentsEHR /></Protected>} />
            <Route path="/portal/provider/availability" element={<Protected roles={["practitioner", "admin"]}><Availability /></Protected>} />
            <Route path="/portal/provider/messages" element={<Protected roles={["practitioner", "admin", "medical_assistant"]}><Messages /></Protected>} />
            <Route path="/portal/provider/security" element={<Protected roles={PROVIDER_ROLES}><Security /></Protected>} />
            <Route path="/portal/provider/account" element={<Protected roles={PROVIDER_ROLES}><MyAccount /></Protected>} />
            <Route path="/portal/provider/front-desk" element={<Protected roles={PROVIDER_ROLES}><FrontDesk /></Protected>} />
            <Route path="/portal/provider/time-clock" element={<Protected roles={PROVIDER_ROLES}><TimeClock /></Protected>} />
            <Route path="/portal/provider/treatments" element={<Protected roles={PROVIDER_ROLES}><Treatments /></Protected>} />
            <Route path="/portal/provider/pos" element={<Protected roles={FRONT_DESK_ROLES}><PointOfSale /></Protected>} />
            <Route path="/portal/provider/transactions" element={<Protected roles={[...FRONT_DESK_ROLES, "auditor"]}><Transactions /></Protected>} />
            <Route path="/portal/provider/inventory" element={<Protected roles={FRONT_DESK_ROLES}><Inventory /></Protected>} />

            {/* Admin */}
            <Route path="/portal/admin" element={<Protected roles={["admin"]}><AdminOverview /></Protected>} />
            <Route path="/portal/admin/users" element={<Protected roles={["admin"]}><AdminUsers /></Protected>} />
            <Route path="/portal/admin/audit" element={<Protected roles={["admin"]}><AdminAudit /></Protected>} />
            <Route path="/portal/admin/sessions" element={<Protected roles={["admin"]}><AdminSessionExplorer /></Protected>} />
            <Route path="/portal/admin/reminders" element={<Protected roles={["admin"]}><AdminReminders /></Protected>} />
            <Route path="/portal/admin/security" element={<Protected roles={["admin"]}><Security /></Protected>} />
            <Route path="/portal/admin/account" element={<Protected roles={["admin"]}><MyAccount /></Protected>} />
            <Route path="/portal/admin/front-desk" element={<Protected roles={["admin"]}><FrontDesk /></Protected>} />
            <Route path="/portal/admin/time-clock" element={<Protected roles={["admin"]}><TimeClock /></Protected>} />
            <Route path="/portal/admin/treatments" element={<Protected roles={["admin"]}><Treatments /></Protected>} />
            <Route path="/portal/admin/pos" element={<Protected roles={["admin"]}><PointOfSale /></Protected>} />
            <Route path="/portal/admin/transactions" element={<Protected roles={["admin"]}><Transactions /></Protected>} />
            <Route path="/portal/admin/inventory" element={<Protected roles={["admin"]}><Inventory /></Protected>} />
            <Route path="/portal/admin/import-clients" element={<Protected roles={["admin"]}><ImportClients /></Protected>} />
            <Route path="/portal/admin/analytics" element={<Protected roles={["admin"]}><Analytics /></Protected>} />
            <Route path="/portal/admin/notes" element={<Protected roles={["admin", "practitioner"]}><AdminNotesList /></Protected>} />
            <Route path="/portal/admin/files" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFilesList /></Protected>} />
            <Route path="/portal/admin/forms" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFormsConsents /></Protected>} />
            <Route path="/portal/staff/forms" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFormsConsents /></Protected>} />
            <Route path="/portal/provider/forms" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFormsConsents /></Protected>} />
            {/* SOAP Notes hub (provider/admin/staff) */}
            <Route path="/portal/admin/soap" element={<Protected roles={["admin", "practitioner", "staff"]}><SoapNotes /></Protected>} />
            <Route path="/portal/staff/soap" element={<Protected roles={["admin", "practitioner", "staff"]}><SoapNotes /></Protected>} />
            <Route path="/portal/provider/soap" element={<Protected roles={["admin", "practitioner", "staff"]}><SoapNotes /></Protected>} />
            {/* Protocols (provider/admin only — staff read via enrollments) */}
            <Route path="/portal/admin/protocols" element={<Protected roles={["admin", "practitioner", "staff"]}><Protocols /></Protected>} />
            <Route path="/portal/staff/protocols" element={<Protected roles={["admin", "practitioner", "staff"]}><Protocols /></Protected>} />
            <Route path="/portal/provider/protocols" element={<Protected roles={["admin", "practitioner", "staff"]}><Protocols /></Protected>} />
            {/* Patient self-service */}
            <Route path="/portal/patient/protocols" element={<Protected roles={["client"]}><PatientProtocols /></Protected>} />
            {/* Document Library — universal AI ingest */}
            <Route path="/portal/admin/library" element={<Protected roles={["admin", "practitioner", "staff"]}><DocumentLibrary /></Protected>} />
            <Route path="/portal/staff/library" element={<Protected roles={["admin", "practitioner", "staff"]}><DocumentLibrary /></Protected>} />
            <Route path="/portal/provider/library" element={<Protected roles={["admin", "practitioner", "staff"]}><DocumentLibrary /></Protected>} />
            <Route path="/portal/admin/compliance" element={<Protected roles={["admin"]}><AdminCompliance /></Protected>} />
            <Route path="/portal/provider/analytics" element={<Protected roles={["practitioner", "admin"]}><Analytics /></Protected>} />

            {/* Public form responder (token-based, no login required) */}
            <Route path="/forms/respond/:token" element={<FormResponder />} />
          </Routes>
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
      </ErrorBoundary>
    </div>
  );
}

export default App;
