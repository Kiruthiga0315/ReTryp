import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { DashboardPayload } from "../api/types";

/** The traveller's current journey, shared by the header and the dashboard. */
export function useCurrentTrip() {
  return useQuery({
    queryKey: ["trip", "current"],
    queryFn: api.currentTrip,
    select: (data): DashboardPayload => data.trip,
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  });
}

/** Which real sources are answering, for the header badge and sign-in notice. */
export function useDataStatus() {
  return useQuery({
    queryKey: ["data-status"],
    queryFn: api.dataStatus,
    staleTime: 5 * 60 * 1000,
  });
}

export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.notifications(),
    enabled,
    staleTime: 10_000,
  });
}

export function useTripId(): string | null {
  const trip = useCurrentTrip();
  return trip.data?.trip.id ?? null;
}
