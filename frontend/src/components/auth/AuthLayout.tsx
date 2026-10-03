import { Link } from "react-router-dom";
import { useDataStatus } from "../../hooks/useTrip";
import { Banner } from "../ui/Card";
import { Icon } from "../ui/Icon";
import { ProvenanceBadge } from "../ui/Badge";
import type { ReactNode } from "react";

const PROMISES = [
  "Detects a disruption and traces the cascading effects",
  "Builds several complete plans, not just the cheapest",
  "Shows every data point with its provenance",
  "Books nothing without your explicit confirmation",
];

/** The two-column sign-in / sign-up shell. The left panel is the same on both. */
export function AuthLayout({ children }: { children: ReactNode }) {
  const dataStatus = useDataStatus();

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        backgroundColor: "var(--surface-page)",
      }}
    >
      <div
        style={{
          position: "relative",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "var(--s-9) var(--s-8)",
          color: "var(--white)",
          background: "url('https://images.unsplash.com/photo-1542314831-c6a4d14eff4c?q=80&w=2000&auto=format&fit=crop') center/cover no-repeat",
        }}
        className="signin-aside"
      >
        {/* Dark overlay for text legibility */}
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to bottom, rgba(14,22,33,0.3) 0%, rgba(14,22,33,0.8) 100%)", zIndex: 0 }}></div>
        
        <div className="row row-3" style={{ position: "relative", zIndex: 1 }}>
          <span
            style={{
              width: 32,
              height: 32,
              borderRadius: "var(--radius)",
              background: "rgba(255, 255, 255, 0.15)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "1px solid rgba(255,255,255,0.2)"
            }}
          >
            <Icon name="Route" size={18} strokeWidth={2} />
          </span>
          <span style={{ fontSize: "var(--text-xl)", fontWeight: 700, letterSpacing: "-0.01em", fontFamily: "var(--font-display)" }}>
            ReTryp
          </span>
        </div>

        <div style={{ maxWidth: 480, position: "relative", zIndex: 1 }}>
          <h1 className="h1" style={{ color: "var(--white)", marginBottom: "var(--s-4)" }}>
            Autonomous trip recovery.
          </h1>
          <p style={{ color: "rgba(255,255,255,0.85)", fontSize: "var(--text-md)", lineHeight: 1.6 }}>
            ReTryp holds a traveller's whole journey in one place: flights, rail, transfers and
            hotels. When a leg breaks, it works out the effect on everything downstream, builds
            complete recovery plans, compares them, and executes the one you approve.
          </p>
          <ul style={{ marginTop: "var(--s-6)", display: "flex", flexDirection: "column", gap: "var(--s-3)" }}>
            {PROMISES.map((line) => (
              <li key={line} className="row row-3" style={{ color: "rgba(255,255,255,0.75)" }}>
                <Icon name="Check" size={16} />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="tiny" style={{ color: "rgba(255,255,255,0.5)", position: "relative", zIndex: 1 }}>
          Times are stored in UTC and shown in the local zone of each airport, station or hotel.
        </p>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "var(--s-6)" }}>
        <div style={{ width: "100%", maxWidth: 400 }}>
          {dataStatus.data ? (
            <div style={{ marginBottom: "var(--s-5)" }}>
              <Banner tone="info" icon="Info" title="Data sources">
                <div className="row row-2 wrap">
                  <ProvenanceBadge
                    value={
                      dataStatus.data.mode === "live"
                        ? "LIVE"
                        : dataStatus.data.mode === "reference"
                          ? "REFERENCE"
                          : "UNAVAILABLE"
                    }
                  />
                  <span>{dataStatus.data.note}</span>
                </div>
              </Banner>
            </div>
          ) : null}
          {children}
          <p className="tiny muted" style={{ marginTop: "var(--s-6)" }}>
            <Link to="/signin">Sign in</Link> · <Link to="/signup">Create an account</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
