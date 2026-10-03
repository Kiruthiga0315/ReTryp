import { NavLink, useLocation } from "react-router-dom";
import { Icon } from "../ui/Icon";

export interface NavItem {
  to: string;
  label: string;
  icon: string;
  count?: number;
  end?: boolean;
}

export function Sidebar({
  items,
  collapsed,
  onToggleCollapsed,
  mobileOpen,
  onCloseMobile,
}: {
  items: NavItem[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const location = useLocation();

  return (
    <nav
      className="sidebar"
      aria-label="Main navigation"
      data-mobile-open={mobileOpen}
    >
      <div className="sidebar__brand">
        <span className="sidebar__mark">
          <Icon name="Route" size={16} strokeWidth={2.25} />
        </span>
        <span className="sidebar__wordmark">ReTryp</span>
      </div>

      <div className="sidebar__nav">
        <div className="sidebar__section">Journey</div>
        {items.slice(0, 5).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `sidebar__link ${isActive ? "is-active" : ""}`}
            onClick={onCloseMobile}
            aria-current={location.pathname === item.to ? "page" : undefined}
            title={collapsed ? item.label : undefined}
          >
            <Icon name={item.icon} size={17} />
            <span>{item.label}</span>
            {item.count ? <span className="sidebar__count">{item.count}</span> : null}
          </NavLink>
        ))}

        <div className="sidebar__section">Account</div>
        {items.slice(5).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `sidebar__link ${isActive ? "is-active" : ""}`}
            onClick={onCloseMobile}
            title={collapsed ? item.label : undefined}
          >
            <Icon name={item.icon} size={17} />
            <span>{item.label}</span>
            {item.count ? <span className="sidebar__count">{item.count}</span> : null}
          </NavLink>
        ))}
      </div>

      <div className="sidebar__footer">
        <button
          type="button"
          className="sidebar__collapse"
          onClick={onToggleCollapsed}
          aria-pressed={collapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <Icon name={collapsed ? "PanelLeft" : "PanelLeftClose"} size={17} />
          <span>Collapse</span>
        </button>
      </div>
    </nav>
  );
}
