import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useCurrentTrip } from "../hooks/useTrip";
import { api } from "../api/client";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { ProvenanceBadge, StatusChip, Chip } from "../components/ui/Badge";
import { Icon, modeIcon } from "../components/ui/Icon";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, SkeletonPage } from "../components/ui/States";
import { TripMap } from "../components/domain/TripMap";
import { NetworkPanel } from "../components/domain/NetworkPanel";

export function MapPage() {
  const trip = useCurrentTrip();
  const navigate = useNavigate();
  const [transit, setTransit] = useState<{ lat: number; lon: number; radius: number } | null>(null);
  const recovery = useQuery({
    queryKey: ["recovery", trip.data?.trip.id],
    queryFn: () => api.recovery(trip.data!.trip.id),
    enabled: Boolean(trip.data?.trip.id),
  });
  const nearby = useQuery({
    queryKey: ["journey-transit-near", transit?.lat, transit?.lon, transit?.radius],
    queryFn: () => api.journeyTransitNear(transit!.lat, transit!.lon, transit!.radius),
    enabled: Boolean(transit),
    staleTime: 30 * 60 * 1000,
  });

  if (trip.isLoading) return <SkeletonPage />;
  if (trip.isError) {
    return (
      <ErrorState
        title="Cannot load the map"
        message={(trip.error as Error)?.message ?? "No current journey was returned."}
        onRetry={() => void trip.refetch()}
      />
    );
  }
  if (!trip.data) {
    return (
      <EmptyState
        icon="MapPin"
        title="No journey to map"
        actions={
          <Button variant="primary" icon="Plus" onClick={() => navigate("/build")}>
            Build a journey
          </Button>
        }
      >
        <p>
          Once you build a journey its airports, stations and hotels appear here on
          the map, with the original and recovered routes drawn separately.
        </p>
      </EmptyState>
    );
  }

  const data = trip.data;
  const plan = recovery.data?.active_plan ?? recovery.data?.plans.find((p) => p.recommended) ?? null;
  const places = Array.from(
    new Map(
      data.segments
        .flatMap((segment) => [segment.origin, segment.destination])
        .map((place) => [place.code, place]),
    ).values(),
  );

  return (
    <>
      <PageHeader
        title="Trip map"
        subtitle="Airports, stations, hotels, the original route and the recovered route"
        actions={
          <>
            <ProvenanceBadge value={data.trip.provenance} />
            <Chip variant="info" icon="Globe">
              OpenStreetMap tiles
            </Chip>
          </>
        }
      />

      <div className="stack stack-5">
        <Card>
          <CardBody tight>
            <TripMap
              segments={data.segments}
              hotels={data.hotels}
              ground={data.ground}
              plan={plan}
              currentPlaceCode={data.current_location?.place_code}
              transitNodes={nearby.data?.nodes}
              onPick={(lat, lon) => setTransit({ lat, lon, radius: 15 })}
            />
          </CardBody>
        </Card>

        <NetworkPanel nearby={nearby} onPick={(lat, lon) => setTransit({ lat, lon, radius: 15 })} />

        <div className="grid grid-3">
          <Card>
            <CardHeader title="Places on this journey" icon="MapPin" />
            <CardBody flush>
              <div className="list-rows">
                {places.map((place) => (
                  <div key={place.code} className="row row-3" style={{ padding: "var(--s-3) var(--s-5)" }}>
                    <Icon name={place.code.length > 3 ? "TrainFront" : "Plane"} size={16} />
                    <div className="grow">
                      <div style={{ fontWeight: 500 }}>
                        {place.code} · {place.city}
                      </div>
                      <div className="tiny muted">{place.name}</div>
                    </div>
                    <span className="tag">{place.timezone}</span>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Accommodation" icon="BedDouble" />
            <CardBody flush>
              {data.hotels.map((hotel) => (
                <div key={hotel.id} style={{ padding: "var(--s-3) var(--s-5)" }}>
                  <div style={{ fontWeight: 500 }}>{hotel.name}</div>
                  <div className="tiny muted">{hotel.address}</div>
                  <div className="row row-2 wrap" style={{ marginTop: "var(--s-2)" }}>
                    <StatusChip kind="hotel" value={hotel.status} size="sm" />
                    <ProvenanceBadge value={hotel.provenance} />
                  </div>
                </div>
              ))}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Recovered legs" subtitle="Drawn in a distinct colour" icon="Route" />
            <CardBody flush>
              {plan && plan.segments.length > 0 ? (
                <div className="list-rows">
                  {plan.segments.map((segment) => (
                    <div key={segment.key} className="row row-3" style={{ padding: "var(--s-3) var(--s-5)" }}>
                      <Icon name={modeIcon(segment.mode)} size={16} />
                      <div className="grow">
                        <div style={{ fontWeight: 500 }}>
                          {segment.origin_code} → {segment.destination_code}
                        </div>
                        <div className="tiny muted">
                          {segment.carrier_name} {segment.service_number} · {segment.arrival_local}
                        </div>
                      </div>
                      <ProvenanceBadge value={segment.provenance} />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="small muted" style={{ padding: "var(--s-5)" }}>
                  No recovered route is active. The journey is running as booked.
                </p>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
