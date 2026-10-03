import type {
  AuditEntry,
  BookingsPayload,
  DashboardPayload,
  DataStatusInfo,
  Disruption,
  JourneyBuildRequest,
  JourneyBuildResult,
  JourneyCheck,
  JourneyBridge,
  JourneyOption,
  JourneyOptionsPayload,
  NetworkSummary,
  TransitNearby,
  JourneyPlace,
  JourneyReason,
  MonitoringResult,
  MonitoringState,
  Notification,
  ProviderHealth,
  RecoveryPayload,
  RecoveryPlan,
  ScenarioCatalog,
  Segment,
  TimelinePayload,
  TripContext,
  TripHistory,
  TripSummary,
  UserProfile,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

function detailFrom(payload: unknown, fallback: string): string {
  if (typeof payload === "string" && payload.trim()) return payload;
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const detail = record.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as Record<string, unknown>;
      if (typeof first?.msg === "string") return first.msg;
    }
  }
  return fallback;
}

async function request<T>(
  path: string,
  init: RequestInit & { query?: Record<string, string | number | boolean | undefined> } = {},
): Promise<T> {
  const { query, ...rest } = init;
  let url = `${BASE}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(rest.body ? { "Content-Type": "application/json" } : {}),
        ...(rest.headers ?? {}),
      },
      ...rest,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the ReTryp API. Check that the backend is running.");
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      detailFrom(payload, `Request failed with status ${response.status}`),
    );
  }
  return payload as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export const api = {
  /* ------------------------------------------------------------ auth */
  signin: (email: string, password: string) =>
    post<{ user: UserProfile }>("/auth/signin", { email, password }),

  signup: (payload: {
    email: string;
    password: string;
    full_name: string;
    role?: string;
    home_airport?: string;
  }) => post<{ user: UserProfile }>("/auth/signup", payload),

  signout: () => post<{ ok: boolean }>("/auth/signout"),

  me: () => request<{ user: UserProfile }>("/auth/me"),

  updateProfile: (payload: Record<string, unknown>) =>
    patch<{ user: UserProfile }>("/auth/profile", payload),

  updateSettings: (payload: Record<string, unknown>) =>
    patch<{ user: UserProfile }>("/auth/settings", payload),

  /* ------------------------------------------------------- meta / mode */
  dataStatus: () => request<DataStatusInfo>("/data-status"),

  providerHealth: () => request<ProviderHealth>("/providers/health"),

  /* ------------------------------------------------------------ journey */
  journeyReasons: () => request<{ reasons: JourneyReason[] }>("/journey/reasons"),

  journeyPlaces: (q: string, limit = 10) =>
    request<{ query: string; places: JourneyPlace[] }>("/journey/places", {
      query: { q, limit },
    }),

  journeyOptions: (origin: string, destination: string, date: string) =>
    request<JourneyOptionsPayload>("/journey/options", {
      query: { origin, destination, date },
    }),

  journeyTransfers: (city: string, date: string) =>
    request<{ city: string; date: string; options: JourneyOption[]; sources: string[]; notes: string[] }>(
      "/journey/transfers",
      { query: { city, date } },
    ),

  journeyNetwork: () => request<NetworkSummary>("/journey/network"),

  journeyTransitNear: (lat: number, lon: number, radiusKm = 15) =>
    request<TransitNearby>("/journey/transit-near", {
      query: { lat: String(lat), lon: String(lon), radius_km: String(radiusKm) },
    }),

  journeyNearest: (lat: number, lon: number, limit = 8, kinds = "") =>
    request<{
      lat: number;
      lon: number;
      places: {
        code: string;
        name: string;
        city: string;
        country: string;
        kind: string;
        distance_km: number;
        lat: number;
        lon: number;
      }[];
    }>("/journey/nearest", {
      query: { lat: String(lat), lon: String(lon), limit: String(limit), kinds },
    }),

  journeyConnections: (origin: string, destination: string) =>
    request<{
      origin: string;
      destination: string;
      served_directly: boolean;
      path: { code: string; name: string; city: string; kind: string }[];
      connections: JourneyBridge[];
    }>("/journey/connections", { query: { origin, destination } }),

  buildJourney: (payload: JourneyBuildRequest) =>
    post<JourneyBuildResult>("/journey/build", payload),

  checkJourney: (tripId: string) => post<JourneyCheck>(`/journey/${tripId}/check`),

  recoverJourney: (
    tripId: string,
    payload: { disruption_kind: string; service_key?: string | null; delay_minutes?: number },
  ) => post<JourneyBuildResult & { message?: string }>(`/journey/${tripId}/recover`, payload),

  /* -------------------------------------------------------------- trips */
  trips: (params?: { status?: string; q?: string }) =>
    request<{ trips: TripSummary[]; count: number }>("/trips", { query: params }),

  currentTrip: () => request<{ trip: DashboardPayload }>("/trips/current"),

  trip: (tripId: string) => request<{ trip: DashboardPayload }>(`/trips/${tripId}`),

  deleteTrip: (tripId: string) =>
    del<{ deleted: boolean; reference: string }>(`/trips/${tripId}`),

  dashboard: (tripId: string) => request<{ trip: DashboardPayload }>(`/trips/${tripId}/dashboard`),

  timeline: (tripId: string) => request<TimelinePayload>(`/trips/${tripId}/timeline`),

  context: (tripId: string) => request<TripContext>(`/trips/${tripId}/context`),

  bookings: (tripId: string) => request<BookingsPayload>(`/trips/${tripId}/bookings`),

  history: (tripId: string) => request<TripHistory>(`/trips/${tripId}/history`),

  disruptions: (tripId: string) =>
    request<{ disruptions: Disruption[]; active: Disruption[] }>(`/trips/${tripId}/disruptions`),

  monitoring: (tripId: string) => request<MonitoringState>(`/trips/${tripId}/monitoring`),

  checkMonitoring: (tripId: string) =>
    post<MonitoringResult>(`/trips/${tripId}/monitoring/check`),

  /* ----------------------------------------------------------- recovery */
  recovery: (tripId: string) => request<RecoveryPayload>(`/trips/${tripId}/recovery`),

  plan: (planId: string) =>
    request<{
      plan: RecoveryPlan;
      trip: TripSummary;
      original_itinerary: Segment[];
      recovered_itinerary: RecoveryPlan["segments"];
    }>(`/plans/${planId}`),

  approvePlan: (planId: string, confirmation: boolean) =>
    post<{ plan: RecoveryPlan }>(`/plans/${planId}/approve`, { plan_id: planId, confirmation }),

  executePlan: (planId: string) => post<{ plan: RecoveryPlan }>(`/plans/${planId}/execute`),

  rejectPlan: (planId: string, reason?: string) =>
    post<{ plan: RecoveryPlan }>(`/plans/${planId}/reject`, { plan_id: planId, reason }),

  /* ------------------------------------------------------ notifications */
  notifications: (params?: { unread_only?: boolean; kind?: string }) =>
    request<{ notifications: Notification[]; unread_count: number; count: number }>(
      "/notifications",
      { query: params },
    ),

  markNotificationsRead: (payload: { ids?: string[]; all?: boolean }) =>
    post<{ updated: number }>("/notifications/read", {
      notification_ids: payload.ids ?? [],
      all: payload.all ?? false,
    }),

  /* --------------------------------------------------------------- audit */
  audit: (params?: { trip_id?: string; limit?: number }) =>
    request<{ entries: AuditEntry[]; count: number }>("/audit", { query: params }),

  /* ---------------------------------------------------------- simulator */
  scenarios: () => request<ScenarioCatalog>("/simulator/scenarios"),

  inject: (payload: {
    trip_id: string;
    kind: string;
    segment_id?: string | null;
    hotel_id?: string | null;
    ground_id?: string | null;
    delay_minutes?: number | null;
    detail?: string | null;
  }) =>
    post<{
      disruption: Disruption;
      impact: RecoveryPayload["impact"];
      plans: RecoveryPlan[];
      cycle: number;
    }>("/simulator/disruptions", payload),

  resetRecovery: (tripId: string) =>
    post<{
      trip: TripSummary;
      removed: {
        disruptions: number;
        plans: number;
        segments: number;
        ground: number;
        notifications: number;
      };
    }>(`/trips/${tripId}/reset`, {}),

  /* ---------------------------------------------------------------- help */
  help: (payload: { trip_id: string; plan_id?: string | null; topic: string; question?: string }) =>
    post<{ topic: string; answer: string; source: string }>("/help", payload),
};
