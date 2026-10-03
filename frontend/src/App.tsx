import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { useAuth } from "./hooks/useAuth";
import { SkeletonPage } from "./components/ui/States";
import { SignInPage } from "./pages/SignInPage";
import { SignUpPage } from "./pages/SignUpPage";
import { JourneyBuilderPage } from "./pages/JourneyBuilderPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ActiveJourneyPage } from "./pages/ActiveJourneyPage";
import { RecoveryCenterPage } from "./pages/RecoveryCenterPage";
import { PlanDetailPage } from "./pages/PlanDetailPage";
import { MapPage } from "./pages/MapPage";
import { MyTripsPage } from "./pages/MyTripsPage";
import { BookingsPage } from "./pages/BookingsPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SettingsPage } from "./pages/SettingsPage";
import { NotFoundPage } from "./pages/NotFoundPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="page">
        <SkeletonPage />
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export function AppRoutes() {
  const { user, loading } = useAuth();

  return (
    <Routes>
      <Route
        path="/signin"
        element={loading ? <div className="page"><SkeletonPage /></div> : user ? <Navigate to="/" replace /> : <SignInPage />}
      />
      <Route
        path="/signup"
        element={loading ? <div className="page"><SkeletonPage /></div> : user ? <Navigate to="/" replace /> : <SignUpPage />}
      />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="build" element={<JourneyBuilderPage />} />
        <Route path="journey" element={<ActiveJourneyPage />} />
        <Route path="recovery" element={<RecoveryCenterPage />} />
        <Route path="recovery/plans/:planId" element={<PlanDetailPage />} />
        <Route path="map" element={<MapPage />} />
        <Route path="trips" element={<MyTripsPage />} />
        <Route path="bookings" element={<BookingsPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
