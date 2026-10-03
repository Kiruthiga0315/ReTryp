import { useEffect, useState, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar, type NavItem } from "./Sidebar";
import { Topbar } from "./Topbar";
import { useCurrentTrip, useNotifications } from "../../hooks/useTrip";
import { useAuth } from "../../hooks/useAuth";
import { ScenarioSimulator } from "../domain/ScenarioSimulator";
import { ErrorState } from "../ui/States";

export function AppShell() {
  const location = useLocation();
  const { user } = useAuth();
  const trip = useCurrentTrip();
  const notifications = useNotifications(Boolean(user));
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const unread = notifications.data?.unread_count ?? 0;
  const activeDisruptions = trip.data?.trip.active_disruption_count ?? 0;

  const items: NavItem[] = [
    { to: "/build", label: "Build Journey", icon: "Route" },
    { to: "/", label: "Dashboard", icon: "LayoutDashboard", end: true },
    { to: "/trips", label: "My Trips", icon: "BriefcaseBusiness" },
    { to: "/journey", label: "Active Journey", icon: "Navigation" },
    { to: "/map", label: "Trip Map", icon: "MapPin" },
    {
      to: "/recovery",
      label: "Recovery Center",
      icon: "RefreshCw",
      count: activeDisruptions || undefined,
    },
    { to: "/bookings", label: "Bookings", icon: "Ticket" },
    { to: "/notifications", label: "Notifications", icon: "Bell", count: unread || undefined },
    { to: "/history", label: "Trip History", icon: "History" },
    { to: "/profile", label: "Profile", icon: "User" },
    { to: "/settings", label: "Settings", icon: "Settings" },
  ];

  return (
    <div
      className="app-shell"
      data-collapsed={collapsed}
      data-mobile-open={mobileOpen}
    >
      <Sidebar
        items={items}
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((value) => !value)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      {mobileOpen ? <div className="scrim" onClick={() => setMobileOpen(false)} aria-hidden="true" /> : null}

      <div className="app-main">
        <Topbar onOpenMobileNav={() => setMobileOpen(true)} />
        <main className="page">
          {trip.isError ? (
            <ErrorState
              title="Cannot load the current journey"
              message={(trip.error as Error)?.message ?? "The ReTryp API did not respond."}
              onRetry={() => void trip.refetch()}
            />
          ) : (
            <Outlet />
          )}
        </main>
        <ScenarioSimulator />
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumb,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div className="page-header__titles">
        {breadcrumb ? <div className="tiny muted" style={{ marginBottom: 4 }}>{breadcrumb}</div> : null}
        <h1 className="h1">{title}</h1>
        {subtitle ? <div className="page-header__sub">{subtitle}</div> : null}
      </div>
      {actions ? <div className="row row-2 wrap">{actions}</div> : null}
    </div>
  );
}
