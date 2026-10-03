import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { SearchInput, SelectField, Pagination, SortHeader } from "../components/ui/Form";
import { Icon } from "../components/ui/Icon";
import { ConfirmDialog } from "../components/ui/Dialog";
import { useToast } from "../components/ui/Toast";
import { StatusChip } from "../components/ui/Badge";
import { EmptyState, ErrorState, SkeletonTable } from "../components/ui/States";
import { useSort, sortItems, usePagination, useDebounced } from "../hooks/useSort";
import { useAuth } from "../hooks/useAuth";
import type { TripSummary } from "../api/types";

type Field = "name" | "route" | "dates" | "segments" | "status" | "disruptions";

export function MyTripsPage() {
  const trips = useQuery({ queryKey: ["trips"], queryFn: () => api.trips() });
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [disruptionFilter, setDisruptionFilter] = useState("");
  const [pendingDelete, setPendingDelete] = useState<TripSummary | null>(null);
  const { sort, toggle } = useSort<Field>("dates", "desc");
  const debouncedQuery = useDebounced(query);

  const removeTrip = useMutation({
    mutationFn: (tripId: string) => api.deleteTrip(tripId),
    onSuccess: (result) => {
      toast.success("Trip removed", `${result.reference} and its records were deleted.`);
      setPendingDelete(null);
      void queryClient.invalidateQueries({ queryKey: ["trips"] });
      void queryClient.invalidateQueries({ queryKey: ["trip", "current"] });
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.detail : "The trip could not be removed.";
      toast.error("Cannot remove trip", message);
    },
  });

  const canDelete = (trip: TripSummary) =>
    user?.role === "admin" || trip.traveller_id === user?.id;

  const filtered = useMemo(() => {
    let items = trips.data?.trips ?? [];

    if (debouncedQuery.trim()) {
      const needle = debouncedQuery.trim().toLowerCase();
      items = items.filter((trip) =>
        [
          trip.name,
          trip.reference,
          trip.origin_city,
          trip.destination_city,
          trip.origin_code,
          trip.destination_code,
          trip.traveller_name,
        ]
          .join(" ")
          .toLowerCase()
          .includes(needle),
      );
    }

    if (statusFilter) items = items.filter((trip) => trip.status === statusFilter);

    if (disruptionFilter === "active") {
      items = items.filter((trip) => trip.active_disruption_count > 0);
    } else if (disruptionFilter === "none") {
      items = items.filter((trip) => trip.active_disruption_count === 0);
    }

    return items;
  }, [trips.data, debouncedQuery, statusFilter, disruptionFilter]);

  const sorted = sortItems(filtered, sort, {
    name: (a: TripSummary, b: TripSummary) => a.name.localeCompare(b.name),
    route: (a: TripSummary, b: TripSummary) =>
      `${a.origin_city}${a.destination_city}`.localeCompare(`${b.origin_city}${b.destination_city}`),
    dates: (a: TripSummary, b: TripSummary) =>
      new Date(a.starts_at_utc).getTime() - new Date(b.starts_at_utc).getTime(),
    segments: (a: TripSummary, b: TripSummary) => a.segment_count - b.segment_count,
    status: (a: TripSummary, b: TripSummary) => a.status.localeCompare(b.status),
    disruptions: (a: TripSummary, b: TripSummary) => a.disruption_count - b.disruption_count,
  });

  const { page, pageSize, setPage, start, end } = usePagination(sorted.length, 10);
  const visible = sorted.slice(start, end);

  if (trips.isLoading) return <SkeletonTable rows={6} columns={5} />;
  if (trips.isError) {
    return (
      <ErrorState
        title="Cannot load your trips"
        message={(trips.error as Error)?.message ?? "The trips list could not be loaded."}
        onRetry={() => void trips.refetch()}
      />
    );
  }

  return (
    <>
      <PageHeader
        title="My Trips"
        subtitle={`${sorted.length} of ${trips.data?.count ?? 0} trips`}
      />

      <Card>
        <CardBody>
          <div className="filter-bar">
            <SearchInput
              value={query}
              onChange={setQuery}
              placeholder="Search by name, route, reference or traveller"
              ariaLabel="Search trips"
            />
            <div style={{ minWidth: 180 }}>
              <SelectField
                label=""
                value={statusFilter}
                onChange={setStatusFilter}
                placeholder="All statuses"
                options={[
                  { value: "scheduled", label: "On track" },
                  { value: "at_risk", label: "At risk" },
                  { value: "disrupted", label: "Disrupted" },
                  { value: "recovering", label: "Recovery in progress" },
                  { value: "completed", label: "Completed" },
                ]}
              />
            </div>
            <div style={{ minWidth: 180 }}>
              <SelectField
                label=""
                value={disruptionFilter}
                onChange={setDisruptionFilter}
                placeholder="Any disruption state"
                options={[
                  { value: "active", label: "With active disruption" },
                  { value: "none", label: "No active disruption" },
                ]}
              />
            </div>
          </div>
        </CardBody>
      </Card>

      <div style={{ marginTop: "var(--s-4)" }}>
        <Card>
          <CardHeader title="Trips" subtitle="Sort any column" icon="BriefcaseBusiness" />
          {visible.length === 0 ? (
            <EmptyState icon="Search" title="No trips match those filters">
              Clear the search or filters to see every trip on the account.
            </EmptyState>
          ) : (
            <>
              <CardBody flush>
                <div className="table-wrap">
                  <table className="table">
                    <caption className="visually-hidden">Your trips</caption>
                    <thead>
                      <tr>
                        <SortHeader field="name" label="Trip" sort={sort} onSort={toggle} />
                        <SortHeader field="route" label="Route" sort={sort} onSort={toggle} />
                        <SortHeader field="dates" label="Dates" sort={sort} onSort={toggle} />
                        <SortHeader field="segments" label="Segments" sort={sort} onSort={toggle} numeric />
                        <th>Hotels</th>
                        <th>Ground</th>
                        <SortHeader field="disruptions" label="Disruptions" sort={sort} onSort={toggle} numeric />
                        <SortHeader field="status" label="Status" sort={sort} onSort={toggle} />
                        <th>
                          <span className="visually-hidden">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {visible.map((trip) => (
                        <tr key={trip.id}>
                          <td>
                            <div className="cell-primary">{trip.name}</div>
                            <div className="cell-sub">
                              <span className="mono">{trip.reference}</span> · {trip.traveller_name}
                            </div>
                          </td>
                          <td>
                            <div>
                              {trip.origin_city} ({trip.origin_code}) → {trip.destination_city} (
                              {trip.destination_code})
                            </div>
                            <div className="cell-sub">{trip.purpose ?? "—"}</div>
                          </td>
                          <td>
                            <div className="numeric small">{trip.starts_at_local}</div>
                            <div className="cell-sub">{trip.ends_at_local}</div>
                          </td>
                          <td className="is-numeric">{trip.segment_count}</td>
                          <td>
                            <span className="row row-2">
                              <Icon name="BedDouble" size={13} />
                              {trip.hotel_count}
                            </span>
                          </td>
                          <td>
                            <span className="row row-2">
                              <Icon name="CarFront" size={13} />
                              {trip.ground_count}
                            </span>
                          </td>
                          <td className="is-numeric">
                            {trip.disruption_count}
                            {trip.active_disruption_count > 0 ? (
                              <span className="tiny" style={{ color: "var(--status-disrupted)" }}>
                                {" "}
                                ({trip.active_disruption_count} active)
                              </span>
                            ) : null}
                          </td>
                          <td>
                            <StatusChip kind="trip" value={trip.status} size="sm" />
                          </td>
                          <td>
                            {canDelete(trip) ? (
                              trip.active_disruption_count > 0 ? (
                                <button
                                  type="button"
                                  className="btn btn--ghost btn--icon"
                                  disabled
                                  aria-label={`Removing ${trip.name} is unavailable while a recovery is in progress`}
                                  title="A recovery is in progress. Resolve it before removing the trip."
                                >
                                  <Icon name="Trash2" size={15} />
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  className="btn btn--ghost btn--icon"
                                  aria-label={`Remove ${trip.name}`}
                                  title="Remove trip"
                                  onClick={() => setPendingDelete(trip)}
                                >
                                  <Icon name="Trash2" size={15} />
                                </button>
                              )
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardBody>
              <Pagination
                page={page}
                pageSize={pageSize}
                total={sorted.length}
                onPage={setPage}
                noun="trips"
              />
            </>
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) removeTrip.mutate(pendingDelete.id);
        }}
        title="Remove this trip?"
        confirmLabel="Remove trip"
        confirmVariant="danger"
        busy={removeTrip.isPending}
      >
        <p>
          <strong>{pendingDelete?.name}</strong> ({pendingDelete?.reference}) and everything
          derived from it — segments, hotel, ground transport, disruptions, plans and
          notifications — will be deleted.
        </p>
        <p className="small muted">
          This cannot be undone. Bookings held with providers are not cancelled by this.
        </p>
      </ConfirmDialog>
    </>
  );
}
