import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "../ui/Icon";
import { ProvenanceBadge } from "../ui/Badge";
import { initials } from "../../lib/format";
import { useAuth } from "../../hooks/useAuth";
import { useCurrentTrip, useDataStatus, useNotifications } from "../../hooks/useTrip";
import type { DataSourceInfo, DataStatus, Provenance } from "../../api/types";

export function Topbar({ onOpenMobileNav }: { onOpenMobileNav: () => void }) {
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const trip = useCurrentTrip();
  const dataStatus = useDataStatus();
  const notifications = useNotifications(Boolean(user));
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeResult, setActiveResult] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) setQuery("");
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const results = useMemo(() => {
    if (!trip.data || query.trim().length < 2) return [];
    const needle = query.trim().toLowerCase();
    const found: { kind: string; title: string; sub: string; to: string }[] = [];

    for (const segment of trip.data.segments) {
      const haystack = [
        segment.service_number,
        segment.carrier_name,
        segment.origin.code,
        segment.origin.name,
        segment.origin.city,
        segment.destination.code,
        segment.destination.name,
        segment.destination.city,
        segment.booking_reference,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (haystack.includes(needle)) {
        found.push({
          kind: "Segment",
          title: `${segment.service_number ?? segment.mode_label} ${segment.origin.code} → ${segment.destination.code}`,
          sub: `${segment.effective_departure_local} · ${segment.booking_reference ?? "No reference"}`,
          to: "/journey",
        });
      }
    }

    for (const hotel of trip.data.hotels) {
      const haystack = [hotel.name, hotel.city_name, hotel.booking_reference]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (haystack.includes(needle)) {
        found.push({
          kind: "Hotel",
          title: hotel.name,
          sub: `${hotel.city_name} · ${hotel.check_in_local}`,
          to: "/bookings",
        });
      }
    }

    if (trip.data.trip.name.toLowerCase().includes(needle)) {
      found.unshift({
        kind: "Trip",
        title: trip.data.trip.name,
        sub: `${trip.data.trip.reference} · ${trip.data.trip.origin_city} to ${trip.data.trip.destination_city}`,
        to: "/",
      });
    }

    return found.slice(0, 8);
  }, [trip.data, query]);

  const unread = notifications.data?.unread_count ?? 0;

  function commitResult(index: number) {
    const result = results[index];
    if (!result) return;
    setQuery("");
    navigate(result.to);
  }

  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-btn topbar__mobile-toggle"
        onClick={onOpenMobileNav}
        aria-label="Open navigation"
      >
        <Icon name="Menu" size={19} />
      </button>

      <div className="topbar__search" ref={searchRef}>
        <input
          className="input input--search"
          type="search"
          value={query}
          placeholder="Search trips, segments, hotels, references"
          aria-label="Global search"
          role="combobox"
          aria-expanded={results.length > 0}
          aria-controls="global-search-results"
          onChange={(event) => {
            setQuery(event.target.value);
            setActiveResult(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveResult((index) => Math.min(index + 1, results.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveResult((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter") {
              commitResult(activeResult);
            } else if (event.key === "Escape") {
              setQuery("");
            }
          }}
        />
        {results.length > 0 ? (
          <div className="topbar__search-results" id="global-search-results" role="listbox">
            {results.map((result, index) => (
              <button
                key={`${result.kind}-${result.title}-${index}`}
                type="button"
                role="option"
                aria-selected={index === activeResult}
                className="search-result"
                data-active={index === activeResult}
                onMouseEnter={() => setActiveResult(index)}
                onClick={() => commitResult(index)}
              >
                <div className="search-result__kind">{result.kind}</div>
                <div className="search-result__title">{result.title}</div>
                <div className="search-result__sub">{result.sub}</div>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="topbar__spacer" />

      <div className="topbar__actions">
        {trip.data ? (
          <Link to="/journey" className="journey-chip" title="Current journey">
            <Icon name="Navigation" size={13} />
            <span className="journey-chip__route">
              {trip.data.trip.origin_code} → {trip.data.trip.destination_code}
            </span>
            <span className="journey-chip__ref">{trip.data.trip.reference}</span>
          </Link>
        ) : null}

        {dataStatus.data ? (
          <DataStatusIndicator
            mode={dataStatus.data.mode}
            note={dataStatus.data.note}
            sources={dataStatus.data.sources}
          />
        ) : null}

        <Link to="/notifications" className="icon-btn" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
          <Icon name={unread ? "BellRing" : "Bell"} size={18} />
          {unread > 0 ? <span className="icon-btn__dot">{unread > 9 ? "9+" : unread}</span> : null}
        </Link>

        <div className="usermenu" ref={menuRef}>
          <button
            type="button"
            className="usermenu__trigger"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
          >
            <span className="avatar">{initials(user?.full_name ?? "?")}</span>
            <span className="usermenu__name">{user?.full_name ?? "Account"}</span>
            <Icon name="ChevronDown" size={14} />
          </button>
          {menuOpen ? (
            <div className="menu" role="menu">
              <div className="menu__header">
                <div style={{ fontWeight: 600 }}>{user?.full_name}</div>
                <div className="tiny muted">{user?.email}</div>
                <div className="row row-2" style={{ marginTop: "var(--s-2)" }}>
                  <span className="tag">
                    <Icon name="User" size={11} />
                    {user?.role === "travel_manager"
                      ? "Travel Manager"
                      : user?.role === "admin"
                        ? "Administrator"
                        : "Traveller"}
                  </span>
                </div>
              </div>
              <Link to="/profile" className="menu__item" role="menuitem" onClick={() => setMenuOpen(false)}>
                <Icon name="User" size={15} />
                Profile
              </Link>
              <Link to="/settings" className="menu__item" role="menuitem" onClick={() => setMenuOpen(false)}>
                <Icon name="Settings" size={15} />
                Settings
              </Link>
              <div className="menu__sep" />
              <button
                type="button"
                className="menu__item"
                role="menuitem"
                onClick={async () => {
                  setMenuOpen(false);
                  await signOut();
                  navigate("/signin");
                }}
              >
                <Icon name="LogOut" size={15} />
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

function DataStatusIndicator({
  mode,
  note,
  sources,
}: {
  mode: DataStatus;
  note: string;
  sources?: DataSourceInfo[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const label = {
    live: "Live data",
    reference: "Reference data",
    unavailable: "No live source",
  }[mode];
  const provenance: Provenance =
    mode === "live" ? "LIVE" : mode === "reference" ? "REFERENCE" : "UNAVAILABLE";

  useEffect(() => {
    if (!open) return;
    function onClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="datamode-wrap" ref={ref}>
      <button
        type="button"
        className="datamode"
        title={note}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((value) => !value)}
      >
        <span className={`datamode__dot datamode__dot--${mode}`} />
        <span className="datamode__label">{label}</span>
        <ProvenanceBadge value={provenance} />
      </button>
      {open ? (
        <div className="datamode__panel" role="dialog" aria-label="Data sources and provenance">
          <p className="datamode__note">{note}</p>
          <table className="datamode__table">
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Provenance</th>
              </tr>
            </thead>
            <tbody>
              {(sources ?? []).map((source) => (
                <tr key={source.name}>
                  <td>
                    <span className="datamode__source">{source.name}</span>
                    <span className="datamode__detail">{source.detail}</span>
                  </td>
                  <td>
                    <ProvenanceBadge value={source.provenance} fetchedAt={source.fetched_at} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
