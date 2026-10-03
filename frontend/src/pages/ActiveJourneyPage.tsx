import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useCurrentTrip } from "../hooks/useTrip";
import { api } from "../api/client";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader, Banner } from "../components/ui/Card";
import { Icon } from "../components/ui/Icon";
import { ProvenanceBadge, StatusChip, Chip } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, SkeletonPage } from "../components/ui/States";
import { SegmentTimelineItem } from "../components/domain/SegmentTimelineItem";
import { TripMap } from "../components/domain/TripMap";
import { duration, zoneFromLocal, money } from "../lib/format";

export function ActiveJourneyPage() {
  const trip = useCurrentTrip();
  const navigate = useNavigate();
  const timeline = useQuery({
    queryKey: ["timeline", trip.data?.trip.id],
    queryFn: () => api.timeline(trip.data!.trip.id),
    enabled: Boolean(trip.data?.trip.id),
  });

  const recovery = useQuery({
    queryKey: ["recovery", trip.data?.trip.id],
    queryFn: () => api.recovery(trip.data!.trip.id),
    enabled: Boolean(trip.data?.trip.id && trip.data?.active_disruption),
  });

  if (trip.isLoading || timeline.isLoading) return <SkeletonPage />;
  if (trip.isError) {
    return (
      <ErrorState
        title="Cannot load the journey"
        message={(trip.error as Error)?.message ?? "No current journey was returned."}
        onRetry={() => void trip.refetch()}
      />
    );
  }
  if (!trip.data) {
    return (
      <EmptyState
        icon="Route"
        title="No active journey"
        actions={
          <Button variant="primary" icon="Plus" onClick={() => navigate("/build")}>
            Build a journey
          </Button>
        }
      >
        <p>
          There is no journey to show yet. Build one from the places you are
          travelling between and its segments will appear here as a timeline.
        </p>
      </EmptyState>
    );
  }

  const data = trip.data;
  const segments = timeline.data?.segments ?? data.segments;
  const hotels = timeline.data?.hotels ?? data.hotels;
  const ground = timeline.data?.ground ?? data.ground;

  // Connection assessments come from the active disruption's impact.
  const connectionByAirport = new Map(
    (recovery.data?.impact?.connections ?? []).map((connection) => [
      connection.airport_code,
      connection,
    ]),
  );

  return (
    <>
      <PageHeader
        title="Active journey"
        subtitle={
          <span className="row row-2 wrap">
            <span className="mono">{data.trip.reference}</span>
            <span aria-hidden="true">·</span>
            <span>
              {data.trip.origin_city} to {data.trip.destination_city}
            </span>
            <span aria-hidden="true">·</span>
            <span>{data.trip.starts_at_local} → {data.trip.ends_at_local}</span>
          </span>
        }
        actions={
          <>
            <StatusChip kind="trip" value={data.trip.status} />
            <ProvenanceBadge value={data.trip.provenance} />
          </>
        }
      />

      {data.active_disruption ? (
        <div style={{ marginBottom: "var(--s-5)" }}>
          <Banner
            tone="disrupted"
            icon="TriangleAlert"
            title={data.active_disruption.title}
            actions={
              <a href="/recovery" className="btn btn--sm btn--primary">
                Recovery Center
              </a>
            }
          >
            {data.active_disruption.detail}
          </Banner>
        </div>
      ) : null}

      <div className="stack stack-5">
        <Card>
          <CardHeader
            title="Timeline"
            subtitle="Scheduled against updated times, in each station's local zone"
            icon="Route"
            actions={
              <span className="row row-2 tiny muted">
                <Icon name="Clock" size={13} />
                All times local
              </span>
            }
          />
          <CardBody>
            <ol className="timeline">
              {segments.map((segment, index) => {
                const connection = connectionByAirport.get(segment.destination.code);
                return (
                  <SegmentTimelineItem
                    key={segment.id}
                    segment={segment}
                    isLast={index === segments.length - 1}
                    connectionNote={
                      connection
                        ? {
                            bufferMinutes: connection.buffer_minutes,
                            requiredMinutes: connection.required_minutes,
                            safety: connection.safety,
                            note: connection.note,
                          }
                        : null
                    }
                  />
                );
              })}
            </ol>
          </CardBody>
        </Card>

        <div className="grid grid-2">
          <Card>
            <CardHeader title="Accommodation" icon="BedDouble" />
            <CardBody flush>
              {hotels.length === 0 ? (
                <p className="small muted" style={{ padding: "var(--s-5)" }}>
                  No hotel booked on this journey.
                </p>
              ) : (
                <div className="list-rows">
                  {hotels.map((hotel) => (
                    <div key={hotel.id} style={{ padding: "var(--s-4) var(--s-5)" }}>
                      <div className="row-between wrap">
                        <div>
                          <div className="h4">{hotel.name}</div>
                          <div className="small muted">{hotel.address}</div>
                        </div>
                        <StatusChip kind="hotel" value={hotel.status} />
                      </div>
                      <div className="grid grid-2" style={{ marginTop: "var(--s-3)", gap: "var(--s-3)" }}>
                        <div>
                          <div className="eyebrow">Check-in</div>
                          <div>{hotel.check_in_local}</div>
                          <div className="tiny muted">{zoneFromLocal(hotel.check_in_local)}</div>
                        </div>
                        <div>
                          <div className="eyebrow">Check-out</div>
                          <div>{hotel.check_out_local}</div>
                          <div className="tiny muted">{zoneFromLocal(hotel.check_out_local)}</div>
                        </div>
                      </div>
                      <div className="row row-2 wrap" style={{ marginTop: "var(--s-3)" }}>
                        <span className="tag">
                          <Icon name="Ticket" size={11} />
                          <span className="mono">{hotel.booking_reference ?? "—"}</span>
                        </span>
                        <span className="tag">{hotel.nights} nights · {hotel.rooms} room</span>
                        <span className="tag">{money(hotel.cost_minor, hotel.cost_currency)}</span>
                        {hotel.late_arrival_notice ? (
                          <Chip variant="risk" icon="Clock">
                            Late-arrival notice active
                          </Chip>
                        ) : null}
                        <ProvenanceBadge value={hotel.provenance} fetchedAt={hotel.fetched_at} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Ground transport" icon="CarFront" />
            <CardBody flush>
              {ground.length === 0 ? (
                <p className="small muted" style={{ padding: "var(--s-5)" }}>
                  No ground transport booked on this journey.
                </p>
              ) : (
                <div className="list-rows">
                  {ground.map((item) => (
                    <div key={item.id} style={{ padding: "var(--s-4) var(--s-5)" }}>
                      <div className="row-between wrap">
                        <div>
                          <div className="h4">
                            {item.mode_label} · {item.provider_name}
                          </div>
                          <div className="small muted">
                            {item.from_label} → {item.to_label}
                          </div>
                        </div>
                        <StatusChip kind="ground" value={item.status} />
                      </div>
                      <div className="row row-2 wrap" style={{ marginTop: "var(--s-3)" }}>
                        <span className="tag">
                          <Icon name="Clock" size={11} />
                          Pickup {item.pickup_local}
                        </span>
                        {item.dropoff_utc ? (
                          <span className="tag">
                            Drop-off {duration(
                              Math.round(
                                (new Date(item.dropoff_utc).getTime() -
                                  new Date(item.pickup_utc).getTime()) /
                                  60000,
                              ),
                            )}
                          </span>
                        ) : null}
                        <span className="tag">{money(item.cost_minor, item.cost_currency)}</span>
                        <span className="tag">
                          <span className="mono">{item.booking_reference ?? "—"}</span>
                        </span>
                        <ProvenanceBadge value={item.provenance} fetchedAt={item.fetched_at} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader title="Map" subtitle="Original route, recovered route and current position" icon="Map" />
          <CardBody tight>
            <TripMap
              segments={segments}
              hotels={hotels}
              ground={ground}
              plan={recovery.data?.active_plan ?? data.recommended_plan}
              currentPlaceCode={data.current_location?.place_code}
            />
          </CardBody>
        </Card>
      </div>
    </>
  );
}
