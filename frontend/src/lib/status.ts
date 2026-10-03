/** Status vocabulary.
 *
 *  Every status renders as colour *and* an icon *and* a text label, never
 *  colour alone. The variant names map onto the palette in tokens.css:
 *  green on time, amber at risk, red disrupted, blue recovery in progress,
 *  grey completed.
 */

export type StatusVariant = "ontime" | "risk" | "disrupted" | "recovery" | "done" | "info";

export interface StatusDescriptor {
  variant: StatusVariant;
  label: string;
  /** lucide-react icon name, resolved in components/ui/Badge.tsx */
  icon: string;
}

const SEGMENT_STATUS: Record<string, StatusDescriptor> = {
  scheduled: { variant: "ontime", label: "On time", icon: "CircleCheck" },
  on_time: { variant: "ontime", label: "On time", icon: "CircleCheck" },
  delayed: { variant: "risk", label: "Delayed", icon: "Clock" },
  at_risk: { variant: "risk", label: "At risk", icon: "TriangleAlert" },
  boarding: { variant: "recovery", label: "Boarding", icon: "DoorOpen" },
  departed: { variant: "recovery", label: "Departed", icon: "PlaneTakeoff" },
  in_progress: { variant: "recovery", label: "In progress", icon: "PlaneTakeoff" },
  cancelled: { variant: "disrupted", label: "Cancelled", icon: "CircleX" },
  missed: { variant: "disrupted", label: "Missed", icon: "CircleX" },
  diverted: { variant: "disrupted", label: "Diverted", icon: "Shuffle" },
  recovered: { variant: "recovery", label: "Recovered", icon: "Route" },
  completed: { variant: "done", label: "Completed", icon: "CircleCheck" },
  arrived: { variant: "done", label: "Arrived", icon: "CircleCheck" },
};

const TRIP_STATUS: Record<string, StatusDescriptor> = {
  scheduled: { variant: "ontime", label: "On track", icon: "CircleCheck" },
  on_track: { variant: "ontime", label: "On track", icon: "CircleCheck" },
  at_risk: { variant: "risk", label: "At risk", icon: "TriangleAlert" },
  disrupted: { variant: "disrupted", label: "Disrupted", icon: "TriangleAlert" },
  recovering: { variant: "recovery", label: "Recovery in progress", icon: "Route" },
  completed: { variant: "done", label: "Completed", icon: "CircleCheck" },
  cancelled: { variant: "done", label: "Cancelled", icon: "CircleX" },
};

const HOTEL_STATUS: Record<string, StatusDescriptor> = {
  confirmed: { variant: "ontime", label: "Confirmed", icon: "CircleCheck" },
  recorded_offline: { variant: "recovery", label: "Recorded offline", icon: "CircleCheck" },
  pending: { variant: "risk", label: "Pending", icon: "Clock" },
  pending_provider: { variant: "risk", label: "Pending provider confirmation", icon: "Clock" },
  late_arrival_notice: { variant: "risk", label: "Late-arrival notice", icon: "Clock" },
  shifted: { variant: "recovery", label: "Shifted one night", icon: "CalendarClock" },
  cancelled: { variant: "disrupted", label: "Cancelled", icon: "CircleX" },
  changed: { variant: "recovery", label: "Changed", icon: "RefreshCw" },
};

const GROUND_STATUS: Record<string, StatusDescriptor> = {
  confirmed: { variant: "ontime", label: "Confirmed", icon: "CircleCheck" },
  recorded_offline: { variant: "recovery", label: "Recorded offline", icon: "CircleCheck" },
  pending: { variant: "risk", label: "Pending", icon: "Clock" },
  requested: { variant: "recovery", label: "Change requested", icon: "Send" },
  cancelled: { variant: "disrupted", label: "Cancelled", icon: "CircleX" },
  rebooked: { variant: "recovery", label: "Rebooked", icon: "RefreshCw" },
  completed: { variant: "done", label: "Completed", icon: "CircleCheck" },
};

const PLAN_STATUS: Record<string, StatusDescriptor> = {
  proposed: { variant: "info", label: "Proposed", icon: "FileText" },
  approved: { variant: "recovery", label: "Approved", icon: "CircleCheck" },
  rejected: { variant: "done", label: "Rejected", icon: "CircleSlash" },
  executing: { variant: "recovery", label: "Executing", icon: "Loader" },
  executed: { variant: "ontime", label: "Executed", icon: "CircleCheck" },
  superseded: { variant: "done", label: "Superseded", icon: "History" },
  expired: { variant: "done", label: "Expired", icon: "History" },
};

const DISRUPTION_STATUS: Record<string, StatusDescriptor> = {
  detected: { variant: "disrupted", label: "Detected", icon: "TriangleAlert" },
  validating: { variant: "risk", label: "Validating", icon: "Search" },
  assessing: { variant: "risk", label: "Assessing impact", icon: "Search" },
  recovering: { variant: "recovery", label: "Recovery in progress", icon: "Route" },
  resolved: { variant: "done", label: "Resolved", icon: "CircleCheck" },
  monitoring: { variant: "recovery", label: "Monitoring", icon: "Activity" },
};

const SEVERITY: Record<string, StatusDescriptor> = {
  low: { variant: "done", label: "Low", icon: "Minus" },
  medium: { variant: "risk", label: "Medium", icon: "TriangleAlert" },
  high: { variant: "disrupted", label: "High", icon: "TriangleAlert" },
  critical: { variant: "disrupted", label: "Critical", icon: "OctagonAlert" },
};

const SAFETY: Record<string, StatusDescriptor> = {
  safe: { variant: "ontime", label: "Connection maintained", icon: "CircleCheck" },
  tight: { variant: "risk", label: "Connection is tight", icon: "Clock" },
  at_risk: { variant: "risk", label: "Connection at risk", icon: "TriangleAlert" },
  broken: { variant: "disrupted", label: "Connection not feasible", icon: "CircleX" },
};

const RISK_LEVEL: Record<string, StatusDescriptor> = {
  low: { variant: "ontime", label: "Low risk", icon: "ShieldCheck" },
  medium: { variant: "risk", label: "Medium risk", icon: "Shield" },
  high: { variant: "disrupted", label: "High risk", icon: "ShieldAlert" },
};

const ACTION_STATUS: Record<string, StatusDescriptor> = {
  pending: { variant: "info", label: "Pending", icon: "Clock" },
  requested: { variant: "recovery", label: "Change requested", icon: "Send" },
  pending_provider: { variant: "risk", label: "Pending provider confirmation", icon: "Clock" },
  recorded_offline: { variant: "recovery", label: "Recorded offline", icon: "CircleCheck" },
  confirmed: { variant: "ontime", label: "Confirmed", icon: "CircleCheck" },
  failed: { variant: "disrupted", label: "Failed", icon: "CircleX" },
};

const COMPENSATION_OUTCOME: Record<string, StatusDescriptor> = {
  eligible: { variant: "ontime", label: "Potential eligibility", icon: "CircleCheck" },
  possibly_eligible: { variant: "risk", label: "Possible eligibility", icon: "TriangleAlert" },
  care_only: { variant: "recovery", label: "Care entitlement", icon: "Info" },
  not_eligible: { variant: "done", label: "Not eligible", icon: "CircleSlash" },
  unknown: { variant: "info", label: "Not assessed", icon: "CircleSlash" },
};

const MAPS: Record<string, Record<string, StatusDescriptor>> = {
  segment: SEGMENT_STATUS,
  trip: TRIP_STATUS,
  hotel: HOTEL_STATUS,
  ground: GROUND_STATUS,
  plan: PLAN_STATUS,
  disruption: DISRUPTION_STATUS,
  severity: SEVERITY,
  safety: SAFETY,
  risk: RISK_LEVEL,
  action: ACTION_STATUS,
  compensation: COMPENSATION_OUTCOME,
};

export function statusOf(
  kind: keyof typeof MAPS | string,
  value: string | null | undefined,
  fallbackLabel?: string,
): StatusDescriptor {
  if (!value) {
    return { variant: "info", label: fallbackLabel ?? "Unknown", icon: "Circle" };
  }
  const map = MAPS[kind];
  const found = map?.[value];
  if (found) return found;
  return {
    variant: "info",
    label: fallbackLabel ?? value.replace(/_/g, " "),
    icon: "Circle",
  };
}
