import type { ReactNode } from "react";
import { Icon, modeIcon } from "./Icon";
import { statusOf, type StatusVariant } from "../../lib/status";
import type { Provenance } from "../../api/types";

/* -------------------------------------------------------------- status */

interface StatusChipProps {
  kind: string;
  value: string | null | undefined;
  label?: string;
  size?: "sm" | "md";
}

/** Colour + icon + text label. Never colour alone. */
export function StatusChip({ kind, value, label, size = "md" }: StatusChipProps) {
  const descriptor = statusOf(kind, value, label);
  return (
    <span className={`badge badge--${descriptor.variant}`}>
      <Icon name={descriptor.icon} size={size === "sm" ? 11 : 12} strokeWidth={2} />
      {label ?? descriptor.label}
    </span>
  );
}

export function Chip({
  variant = "info",
  icon,
  children,
}: {
  variant?: StatusVariant;
  icon?: string;
  children: ReactNode;
}) {
  return (
    <span className={`badge badge--${variant}`}>
      {icon ? <Icon name={icon} size={12} strokeWidth={2} /> : null}
      {children}
    </span>
  );
}

/* ---------------------------------------------------------- provenance */

const PROVENANCE_LABEL: Record<Provenance, string> = {
  LIVE: "Live",
  CACHED: "Cached",
  REFERENCE: "Reference",
  SIMULATED: "Simulated",
  UNAVAILABLE: "Unavailable",
};

const PROVENANCE_TITLE: Record<Provenance, string> = {
  LIVE: "Fetched from a live provider for this request.",
  CACHED: "Served from cache; see the fetched-at time.",
  REFERENCE: "Published reference dataset. Real schedule or reference data, not a live feed.",
  SIMULATED: "Injected by the Scenario Simulator. Not live information.",
  UNAVAILABLE: "No source could answer for this value.",
};

interface ProvenanceBadgeProps {
  value: Provenance | string;
  fetchedAt?: string | null;
}

/** Every outward-facing data point carries its provenance. */
export function ProvenanceBadge({ value, fetchedAt }: ProvenanceBadgeProps) {
  const key = (value?.toUpperCase?.() ?? "UNAVAILABLE") as Provenance;
  const label = PROVENANCE_LABEL[key] ?? String(value);
  const title = PROVENANCE_TITLE[key] ?? "";
  const suffix =
    key === "CACHED" && fetchedAt
      ? ` · fetched ${new Date(fetchedAt).toLocaleString("en-GB", {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })}`
      : "";
  return (
    <span className={`prov prov--${key.toLowerCase()}`} title={`${title}${suffix}`}>
      {label}
      {suffix}
    </span>
  );
}

/* ------------------------------------------------------------ mode icon */

export function ModeIcon({ segmentType, size = 16 }: { segmentType: string; size?: number }) {
  return <Icon name={modeIcon(segmentType)} size={size} />;
}

/* ------------------------------------------------------------ recommended */

export function RecommendedPill() {
  return (
    <span className="pill-recommended">
      <Icon name="CircleCheck" size={12} strokeWidth={2.25} />
      Recommended
    </span>
  );
}

/* ---------------------------------------------------------------- tags */

export function Tag({ icon, children }: { icon?: string; children: ReactNode }) {
  return (
    <span className="tag">
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}
