import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useCurrentTrip } from "../hooks/useTrip";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { Tabs, SearchInput, SortHeader, Pagination } from "../components/ui/Form";
import { Icon, modeIcon } from "../components/ui/Icon";
import { ProvenanceBadge, StatusChip } from "../components/ui/Badge";
import { EmptyState, ErrorState, SkeletonTable } from "../components/ui/States";
import { useSort, sortItems, usePagination } from "../hooks/useSort";
import { money, clockFromLocal, dateFromLocal, zoneFromLocal } from "../lib/format";
import type { GroundTransport, HotelStay, Segment } from "../api/types";

type TabValue = "flights" | "hotels" | "trains" | "ground";
type Field = "reference" | "provider" | "datetime" | "route" | "status" | "cost";

export function BookingsPage() {
  const trip = useCurrentTrip();
  const [tab, setTab] = useState<TabValue>("flights");
  const [query, setQuery] = useState("");

  const bookings = useQuery({
    queryKey: ["bookings", trip.data?.trip.id],
    queryFn: () => api.bookings(trip.data!.trip.id),
    enabled: Boolean(trip.data?.trip.id),
  });

  const { sort, toggle } = useSort<Field>("datetime", "asc");

  // Hooks must run before any early return, so the derived rows are computed
  // here and only rendered conditionally below.
  const data = bookings.data;
  const needle = query.trim().toLowerCase();

  function matches(text: string): boolean {
    return !needle || text.toLowerCase().includes(needle);
  }

  if (trip.isLoading || bookings.isLoading) return <SkeletonTable rows={6} columns={6} />;
  if (bookings.isError || !data) {
    return (
      <ErrorState
        title="Cannot load bookings"
        message={(bookings.error as Error)?.message ?? "The bookings list could not be loaded."}
        onRetry={() => void bookings.refetch()}
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Bookings"
        subtitle={`${data.trip.name} · ${data.trip.reference}`}
        actions={<ProvenanceBadge value={data.trip.provenance} />}
      />

      <Card>
        <CardHeader
          title="All bookings"
          subtitle="Reference, provider, timing, passenger, status and cost"
          icon="Ticket"
          actions={
            <div style={{ minWidth: 240 }}>
              <SearchInput
                value={query}
                onChange={setQuery}
                placeholder="Search reference or provider"
                ariaLabel="Search bookings"
              />
            </div>
          }
        />
        <CardBody flush>
          <div style={{ padding: "0 var(--s-5)" }}>
            <Tabs
              ariaLabel="Booking types"
              value={tab}
              onChange={setTab}
              tabs={[
                { value: "flights", label: "Flights", count: data.counts.flights, icon: "Plane" },
                { value: "hotels", label: "Hotels", count: data.counts.hotels, icon: "BedDouble" },
                { value: "trains", label: "Trains", count: data.counts.trains, icon: "TrainFront" },
                {
                  value: "ground",
                  label: "Ground transport",
                  count: data.counts.ground_transport,
                  icon: "CarFront",
                },
              ]}
            />
          </div>
        </CardBody>

        {tab === "flights" || tab === "trains" ? (
          <TransportTable
            rows={(tab === "flights" ? data.flights : data.trains).filter((row) =>
              matches(`${row.service_number} ${row.carrier_name} ${row.booking_reference}`),
            )}
            sort={sort}
            onSort={toggle}
          />
        ) : null}

        {tab === "hotels" ? (
          <HotelTable
            rows={data.hotels.filter((row) => matches(`${row.name} ${row.booking_reference}`))}
            sort={sort}
            onSort={toggle}
          />
        ) : null}

        {tab === "ground" ? (
          <GroundTable
            rows={data.ground_transport.filter((row) =>
              matches(`${row.provider_name} ${row.booking_reference} ${row.from_label}`),
            )}
            sort={sort}
            onSort={toggle}
          />
        ) : null}
      </Card>
    </>
  );
}

function TransportTable({
  rows,
  sort,
  onSort,
}: {
  rows: Segment[];
  sort: { field: Field; direction: "asc" | "desc" };
  onSort: (field: Field) => void;
}) {
  const { page, pageSize, setPage, start, end } = usePagination(rows.length, 10);

  const sorted = sortItems(rows, sort, {
    reference: (a: Segment, b: Segment) =>
      (a.booking_reference ?? "").localeCompare(b.booking_reference ?? ""),
    provider: (a: Segment, b: Segment) => (a.carrier_name ?? "").localeCompare(b.carrier_name ?? ""),
    datetime: (a: Segment, b: Segment) =>
      new Date(a.scheduled_departure_utc).getTime() - new Date(b.scheduled_departure_utc).getTime(),
    route: (a: Segment, b: Segment) =>
      `${a.origin.code}${a.destination.code}`.localeCompare(`${b.origin.code}${b.destination.code}`),
    status: (a: Segment, b: Segment) => a.status.localeCompare(b.status),
    cost: (a: Segment, b: Segment) => (a.cost_minor ?? 0) - (b.cost_minor ?? 0),
  });

  if (rows.length === 0) {
    return <EmptyState icon="Ticket" title="No bookings in this category" />;
  }

  return (
    <>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <SortHeader field="reference" label="Reference" sort={sort} onSort={onSort} />
              <SortHeader field="provider" label="Provider" sort={sort} onSort={onSort} />
              <SortHeader field="datetime" label="Date and time" sort={sort} onSort={onSort} />
              <SortHeader field="route" label="Origin → destination" sort={sort} onSort={onSort} />
              <th>Passenger</th>
              <SortHeader field="status" label="Status" sort={sort} onSort={onSort} />
              <th>Modification</th>
              <SortHeader field="cost" label="Cost" sort={sort} onSort={onSort} numeric />
            </tr>
          </thead>
          <tbody>
            {sorted.slice(start, end).map((row) => (
              <tr key={row.id}>
                <td>
                  <span className="mono">{row.booking_reference ?? "—"}</span>
                  <div className="cell-sub">
                    <ProvenanceBadge value={row.provenance} />
                  </div>
                </td>
                <td>
                  <div className="cell-primary">{row.carrier_name}</div>
                  <div className="cell-sub">{row.service_number}</div>
                </td>
                <td>
                  <div className="numeric">{clockFromLocal(row.effective_departure_local)}</div>
                  <div className="cell-sub">
                    {dateFromLocal(row.effective_departure_local)} ·{" "}
                    {zoneFromLocal(row.effective_departure_local)}
                  </div>
                </td>
                <td>
                  <div>
                    {row.origin.code} → {row.destination.code}
                  </div>
                  <div className="cell-sub">
                    {row.origin.city} to {row.destination.city}
                  </div>
                </td>
                <td className="small">Lead passenger</td>
                <td>
                  <StatusChip kind="segment" value={row.status} size="sm" />
                </td>
                <td>
                  {row.is_recovery ? (
                    <StatusChip kind="action" value="recorded_offline" size="sm" />
                  ) : row.delay_minutes > 0 ? (
                    <StatusChip kind="action" value="requested" size="sm" />
                  ) : (
                    <span className="small muted">Unchanged</span>
                  )}
                </td>
                <td className="is-numeric">
                  {row.cost_minor !== null && row.cost_currency
                    ? money(row.cost_minor, row.cost_currency)
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={pageSize} total={rows.length} onPage={setPage} noun="bookings" />
    </>
  );
}

function HotelTable({
  rows,
  sort,
  onSort,
}: {
  rows: HotelStay[];
  sort: { field: Field; direction: "asc" | "desc" };
  onSort: (field: Field) => void;
}) {
  if (rows.length === 0) return <EmptyState icon="BedDouble" title="No hotel bookings" />;

  const sorted = sortItems(rows, sort, {
    reference: (a: HotelStay, b: HotelStay) =>
      (a.booking_reference ?? "").localeCompare(b.booking_reference ?? ""),
    provider: (a: HotelStay, b: HotelStay) => a.name.localeCompare(b.name),
    datetime: (a: HotelStay, b: HotelStay) =>
      new Date(a.check_in_utc).getTime() - new Date(b.check_in_utc).getTime(),
    route: (a: HotelStay, b: HotelStay) => a.city_name.localeCompare(b.city_name),
    status: (a: HotelStay, b: HotelStay) => a.status.localeCompare(b.status),
    cost: (a: HotelStay, b: HotelStay) => a.cost_minor - b.cost_minor,
  });

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <SortHeader field="reference" label="Reference" sort={sort} onSort={onSort} />
            <SortHeader field="provider" label="Property" sort={sort} onSort={onSort} />
            <SortHeader field="datetime" label="Check-in" sort={sort} onSort={onSort} />
            <th>Check-out</th>
            <SortHeader field="route" label="City" sort={sort} onSort={onSort} />
            <th>Passenger</th>
            <SortHeader field="status" label="Status" sort={sort} onSort={onSort} />
            <th>Modification</th>
            <SortHeader field="cost" label="Cost" sort={sort} onSort={onSort} numeric />
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.id}>
              <td>
                <span className="mono">{row.booking_reference ?? "—"}</span>
                <div className="cell-sub">
                  <ProvenanceBadge value={row.provenance} />
                </div>
              </td>
              <td>
                <div className="cell-primary">{row.name}</div>
                <div className="cell-sub">
                  {row.nights} nights · {row.rooms} room
                </div>
              </td>
              <td>
                <div className="numeric">{clockFromLocal(row.check_in_local)}</div>
                <div className="cell-sub">{dateFromLocal(row.check_in_local)}</div>
              </td>
              <td>
                <div className="numeric">{clockFromLocal(row.check_out_local)}</div>
                <div className="cell-sub">{dateFromLocal(row.check_out_local)}</div>
              </td>
              <td>{row.city_name}</td>
              <td className="small">Lead passenger</td>
              <td>
                <StatusChip kind="hotel" value={row.status} size="sm" />
              </td>
              <td>
                {row.late_arrival_notice ? (
                  <StatusChip kind="hotel" value="late_arrival_notice" size="sm" />
                ) : (
                  <span className="small muted">Unchanged</span>
                )}
              </td>
              <td className="is-numeric">{money(row.cost_minor, row.cost_currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroundTable({
  rows,
  sort,
  onSort,
}: {
  rows: GroundTransport[];
  sort: { field: Field; direction: "asc" | "desc" };
  onSort: (field: Field) => void;
}) {
  if (rows.length === 0) return <EmptyState icon="CarFront" title="No ground transport bookings" />;

  const sorted = sortItems(rows, sort, {
    reference: (a: GroundTransport, b: GroundTransport) =>
      (a.booking_reference ?? "").localeCompare(b.booking_reference ?? ""),
    provider: (a: GroundTransport, b: GroundTransport) =>
      a.provider_name.localeCompare(b.provider_name),
    datetime: (a: GroundTransport, b: GroundTransport) =>
      new Date(a.pickup_utc).getTime() - new Date(b.pickup_utc).getTime(),
    route: (a: GroundTransport, b: GroundTransport) => a.from_label.localeCompare(b.from_label),
    status: (a: GroundTransport, b: GroundTransport) => a.status.localeCompare(b.status),
    cost: (a: GroundTransport, b: GroundTransport) => a.cost_minor - b.cost_minor,
  });

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <SortHeader field="reference" label="Reference" sort={sort} onSort={onSort} />
            <SortHeader field="provider" label="Provider" sort={sort} onSort={onSort} />
            <SortHeader field="datetime" label="Pickup" sort={sort} onSort={onSort} />
            <SortHeader field="route" label="From → to" sort={sort} onSort={onSort} />
            <th>Passenger</th>
            <SortHeader field="status" label="Status" sort={sort} onSort={onSort} />
            <th>Modification</th>
            <SortHeader field="cost" label="Cost" sort={sort} onSort={onSort} numeric />
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.id}>
              <td>
                <span className="mono">{row.booking_reference ?? "—"}</span>
                <div className="cell-sub">
                  <ProvenanceBadge value={row.provenance} />
                </div>
              </td>
              <td>
                <div className="cell-primary">{row.provider_name}</div>
                <div className="cell-sub">
                  <Icon name={modeIcon(row.mode)} size={11} /> {row.mode_label}
                </div>
              </td>
              <td>
                <div className="numeric">{clockFromLocal(row.pickup_local)}</div>
                <div className="cell-sub">
                  {dateFromLocal(row.pickup_local)} · {zoneFromLocal(row.pickup_local)}
                </div>
              </td>
              <td>
                <div className="small">{row.from_label}</div>
                <div className="cell-sub">{row.to_label}</div>
              </td>
              <td className="small">Lead passenger</td>
              <td>
                <StatusChip kind="ground" value={row.status} size="sm" />
              </td>
              <td>
                {row.status === "cancelled" ? (
                  <StatusChip kind="action" value="requested" size="sm" />
                ) : (
                  <span className="small muted">Unchanged</span>
                )}
              </td>
              <td className="is-numeric">{money(row.cost_minor, row.cost_currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
