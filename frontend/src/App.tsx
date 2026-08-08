import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { AppLayout } from './components/AppLayout';
import { SignIn } from './pages/SignIn';
import { SignUp } from './pages/SignUp';
import { AcceptInvite } from './pages/AcceptInvite';
import { Assistant } from './pages/Assistant';
import { CalendarPage } from './pages/CalendarPage';
import { StaffPage } from './pages/StaffPage';
import { CasesPage } from './pages/CasesPage';
import { CaseDetailPage } from './pages/CaseDetailPage';
import { TranscriberPage } from './pages/TranscriberPage';

function RequireAuth({ children }: { children: JSX.Element }) {
  const { signedIn } = useAuth();
  return signedIn ? children : <Navigate to="/signin" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/signin" element={<SignIn />} />
          <Route path="/signup" element={<SignUp />} />
          <Route path="/invite/:token" element={<AcceptInvite />} />

          <Route
            path="/app"
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="assistant" replace />} />
            <Route path="assistant" element={<Assistant />} />
            <Route path="calendar" element={<CalendarPage />} />
            <Route path="cases" element={<CasesPage />} />
            <Route path="cases/:caseId" element={<CaseDetailPage />} />
            <Route path="transcribe" element={<TranscriberPage />} />
            <Route path="staff" element={<StaffPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/app" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
