import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useCurrentTrip } from "../hooks/useTrip";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader, Banner, MetricRow } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Icon, modeIcon } from "../components/ui/Icon";
import { Chip, ProvenanceBadge, StatusChip } from "../components/ui/Badge";
import { ErrorState, SkeletonPage, EmptyState } from "../components/ui/States";
import { PlanCard } from "../components/domain/PlanCard";
import { TripMap } from "../components/domain/TripMap";

export function DashboardPage() {
  const trip = useCurrentTrip();
  const navigate = useNavigate();

  if (trip.isLoading) return <SkeletonPage />;
  if (trip.isError) {
    return (
      <ErrorState
        title="Cannot load your dashboard"
        message={(trip.error as Error)?.message ?? "No current journey was returned."}
        onRetry={() => void trip.refetch()}
      />
    );
  }

  const data = trip.data ?? null;
  const summary = data?.trip ?? null;

  if (!summary || !data) {
    return (
      <EmptyState
        icon="Route"
        title="No journey yet"
        actions={
          <Button variant="primary" icon="Plus" onClick={() => navigate("/build")}>
            Build a journey
          </Button>
        }
      >
        <p>
          Nothing is planned for you yet. Build a journey from the places you are
          travelling between, pick a service for each leg, and ReTryp will check the
          connections and watch the trip for disruptions.
        </p>
        <p className="small muted">
          We do not preload sample trips. Every row you see is one you created, and each
          data point is badged with where it came from.
        </p>
      </EmptyState>
    );
  }

  const { current_location, next_segment, active_disruption } = data;

  return (
    <>
      <PageHeader
        title={summary.name}
        subtitle={
          <span className="row row-2 wrap">
            <span>
              {summary.origin_city} ({summary.origin_code}) to {summary.destination_city} (
              {summary.destination_code})
            </span>
            <span aria-hidden="true">·</span>
            <span className="mono">{summary.reference}</span>
            <span aria-hidden="true">·</span>
            <span>{summary.traveller_name}</span>
          </span>
        }
        actions={
          <>
            <StatusChip kind="trip" value={summary.status} />
            <ProvenanceBadge value={summary.provenance} />
            <Link to="/journey" className="btn btn--sm">
              <Icon name="Route" size={14} />
              Open journey
            </Link>
          </>
        }
      />

      {active_disruption ? (
        <div style={{ marginBottom: "var(--s-5)" }}>
          <ActiveDisruptionBanner
            disruption={active_disruption}
            planCount={data.recovery_plan_count}
          />
        </div>
      ) : null}

      <div className="stack stack-5">
        {/* Hero Section: The Next Leg & Route */}
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.3fr) minmax(0, 1fr)", gap: "var(--s-5)" }}>
          
          <Card>
            <CardHeader title="Next segment" subtitle="Your immediate next step" icon="Compass" />
            <CardBody>
              {next_segment ? (
                <div className="stack stack-4">
                  <div className="row row-3">
                    <div style={{ background: "var(--surface-inset)", padding: "var(--s-3)", borderRadius: "var(--radius-lg)" }}>
                      <Icon name={modeIcon(next_segment.segment_type)} size={32} style={{ color: "var(--accent-600)" }} />
                    </div>
                    <div>
                      <div className="h2">{next_segment.service_number ?? next_segment.mode_label}</div>
                      <div className="secondary" style={{ marginTop: "var(--s-1)" }}>
                        {next_segment.origin.code} → {next_segment.destination.code} · {next_segment.effective_departure_local}
                      </div>
                    </div>
                  </div>
                  <div className="divider"></div>
                  <div className="row row-between">
                    <StatusChip kind="segment" value={next_segment.status} size="sm" />
                    <Link to="/journey" className="btn btn--sm btn--primary">View full timeline</Link>
                  </div>
                </div>
              ) : (
                <EmptyState icon="Route" title="No further segments" />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Live Map" subtitle="Current progress" icon="Map" />
            <CardBody tight>
              <div style={{ height: "200px" }}>
                <TripMap
                  segments={data.segments}
                  hotels={data.hotels}
                  ground={data.ground}
                  plan={data.recommended_plan}
                  currentPlaceCode={current_location?.place_code}
                />
              </div>
            </CardBody>
          </Card>
        </div>

        {/* Secondary Metrics */}
        <div>
          <h3 className="h4" style={{ marginBottom: "var(--s-3)", color: "var(--text-secondary)" }}>Trip details</h3>
          <div className="grid grid-3">
            <Card>
              <CardBody>
                <div className="eyebrow">Current location</div>
                <div className="h4" style={{ marginTop: "var(--s-1)" }}>{current_location?.label ?? "Unknown"}</div>
                <div className="small muted">{current_location?.detail ?? "No position reported"}</div>
              </CardBody>
            </Card>

            <Card>
              <CardBody>
                <div className="eyebrow">Hotel</div>
                {data.hotels.length > 0 ? (
                  <>
                    <div className="h4" style={{ marginTop: "var(--s-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data.hotels[0].name}</div>
                    <div className="small muted">Check-in {data.hotels[0].check_in_local}</div>
                    <div className="row row-2 wrap" style={{ marginTop: "var(--s-2)" }}>
                      <StatusChip kind="hotel" value={data.hotels[0].status} />
                    </div>
                  </>
                ) : (
                  <p className="small muted" style={{ marginTop: "var(--s-1)" }}>No hotel booked.</p>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardBody>
                <div className="eyebrow">Transfers</div>
                {data.ground.length > 0 ? (
                  <>
                    <div className="h4" style={{ marginTop: "var(--s-1)" }}>{data.ground[0].mode_label}</div>
                    <div className="small muted">Pickup {data.ground[0].pickup_local}</div>
                    <div className="row row-2 wrap" style={{ marginTop: "var(--s-2)" }}>
                      <StatusChip kind="ground" value={data.ground[0].status} />
                    </div>
                  </>
                ) : (
                  <p className="small muted" style={{ marginTop: "var(--s-1)" }}>No transfers booked.</p>
                )}
              </CardBody>
            </Card>
          </div>
        </div>

        {/* recommended plan preview */}
        {active_disruption ? (
          <div>
            <div className="row-between" style={{ marginBottom: "var(--s-3)" }}>
              <div>
                <h2 className="h3">Recommended recovery</h2>
                <p className="small muted">
                  {data.recovery_plan_count} feasible{" "}
                  {data.recovery_plan_count === 1 ? "plan" : "plans"} prepared for this disruption.
                </p>
              </div>
              <Link to="/recovery" className="btn btn--primary btn--sm">
                <Icon name="RefreshCw" size={14} />
                Open Recovery Center
              </Link>
            </div>
            {data.recommended_plan ? (
              <PlanCard plan={data.recommended_plan} />
            ) : (
              <Card>
                <EmptyState
                  icon="Route"
                  title="No plan is ready yet"
                  actions={
                    <Link to="/recovery" className="btn btn--primary">
                      Go to Recovery Center
                    </Link>
                  }
                >
                  Recovery plans are built from available alternatives. Open the Recovery Center to
                  see the current state.
                </EmptyState>
              </Card>
            )}
          </div>
        ) : (
          <Card>
            <EmptyState icon="CircleCheck" title="No active disruption">
              The journey is running to plan. ReTryp keeps monitoring every segment and will raise a
              recovery cycle the moment something breaks.
            </EmptyState>
          </Card>
        )}

        <ContextStrip tripId={summary.id} />
      </div>
    </>
  );
}

function ActiveDisruptionBanner({
  disruption,
  planCount,
}: {
  disruption: { title: string; detail: string; severity: string; kind_label: string; provenance: string; delay_display: string | null; cycle: number };
  planCount: number;
}) {
  return (
    <Banner
      tone="disrupted"
      icon="TriangleAlert"
      title={disruption.title}
      actions={
        <Link to="/recovery" className="btn btn--sm btn--primary">
          Review {planCount} {planCount === 1 ? "plan" : "plans"}
        </Link>
      }
    >
      <div className="row row-2 wrap">
        <StatusChip kind="severity" value={disruption.severity} />
        <span className="tag">{disruption.kind_label}</span>
        {disruption.delay_display ? (
          <span className="tag">
            <Icon name="Clock" size={11} />
            {disruption.delay_display}
          </span>
        ) : null}
        <span className="tag">Recovery cycle {disruption.cycle}</span>
        <ProvenanceBadge value={disruption.provenance} />
      </div>
      <div style={{ marginTop: "var(--s-2)" }}>{disruption.detail}</div>
    </Banner>
  );
}

function ContextStrip({ tripId }: { tripId: string }) {
  const context = useQuery({
    queryKey: ["context", tripId],
    queryFn: () => api.context(tripId),
    staleTime: 5 * 60 * 1000,
  });

  if (!context.data) return null;
  const weather = context.data.weather[0];
  const priors = context.data.delay_priors;

  return (
    <Card>
      <CardHeader
        title="Conditions and punctuality context"
        subtitle="Published aggregates, not per-flight history"
        icon="Globe"
      />
      <CardBody>
        <div className="grid grid-2">
          {weather ? (
            <div>
              <div className="row row-2 wrap">
                <span className="eyebrow">Weather at {weather.place_code}</span>
                <ProvenanceBadge value={weather.provenance} fetchedAt={weather.fetched_at} />
              </div>
              <div className="h4" style={{ marginTop: "var(--s-2)" }}>
                {weather.condition}, {weather.temp_c}°C
              </div>
              <div className="small muted">
                Wind {weather.wind_kph} km/h · {weather.precip_mm} mm rain · visibility{" "}
                {weather.visibility_km} km
              </div>
              <p className="tiny muted" style={{ marginTop: "var(--s-2)" }}>
                {weather.note}
              </p>
            </div>
          ) : null}

          {priors.length > 0 ? (
            <div>
              <div className="row row-2 wrap">
                <span className="eyebrow">Delay context</span>
                <ProvenanceBadge value={priors[0].provenance} />
              </div>
              <div className="stack stack-2" style={{ marginTop: "var(--s-2)" }}>
                {priors.slice(0, 3).map((prior) => (
                  <div key={`${prior.subject}-${prior.scope}`} className="row-between small">
                    <span className="secondary">{prior.sample}</span>
                    <span className="numeric" style={{ fontWeight: 600 }}>
                      {prior.on_time_pct}% on time
                    </span>
                  </div>
                ))}
              </div>
              <p className="tiny muted" style={{ marginTop: "var(--s-2)" }}>
                {context.data.disclaimer}
              </p>
            </div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}
