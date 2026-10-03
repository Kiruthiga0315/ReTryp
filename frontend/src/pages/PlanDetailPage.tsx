import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader, Banner, MetricRow, Divider } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Icon, modeIcon } from "../components/ui/Icon";
import { Chip, ProvenanceBadge, StatusChip, RecommendedPill } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/Dialog";
import { ErrorState, SkeletonPage } from "../components/ui/States";
import { ScoreBreakdown } from "../components/domain/ComparisonTable";
import { CompensationCard, CostBreakdown } from "../components/domain/CompensationCard";
import { HelpPanel } from "../components/domain/HelpPanel";
import { TripMap } from "../components/domain/TripMap";
import { useToast } from "../components/ui/Toast";
import { zoneFromLocal, clockFromLocal, dateFromLocal } from "../lib/format";
import type { RecoveryPlan } from "../api/types";

export function PlanDetailPage() {
  const { planId } = useParams<{ planId: string }>();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const planQuery = useQuery({
    queryKey: ["plan", planId],
    queryFn: () => api.plan(planId!),
    enabled: Boolean(planId),
  });

  const tripId = planQuery.data?.plan.trip_id ?? null;

  const dashboard = useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => api.trip(tripId!),
    enabled: Boolean(tripId),
  });

  const approve = useMutation({
    mutationFn: () => api.approvePlan(planId!, true),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      toast.success("Plan approved", "You can now request execution.");
      setConfirmOpen(false);
    },
    onError: (error: Error) => toast.error("Could not approve the plan", error.message),
  });

  const execute = useMutation({
    mutationFn: () => api.executePlan(planId!),
    onSuccess: (data) => {
      void queryClient.invalidateQueries();
      const recorded = data.plan.actions.filter(
        (action) => action.status === "recorded_offline" || action.status === "confirmed",
      ).length;
      toast.success(
        "Execution recorded",
        recorded > 0
          ? `${recorded} ${recorded === 1 ? "action" : "actions"} recorded.`
          : "Changes requested. No live booking provider is configured.",
      );
    },
    onError: (error: Error) => toast.error("Could not execute the plan", error.message),
  });

  if (planQuery.isLoading) return <SkeletonPage />;
  if (planQuery.isError || !planQuery.data) {
    return (
      <ErrorState
        title="Cannot load this plan"
        message={(planQuery.error as Error)?.message ?? "The plan was not found."}
        onRetry={() => void planQuery.refetch()}
      />
    );
  }

  const { plan, trip, original_itinerary, recovered_itinerary } = planQuery.data;
  const canApprove = plan.status === "proposed";
  const canExecute = plan.status === "approved";

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link to="/recovery" className="row row-2" style={{ display: "inline-flex" }}>
            <Icon name="ChevronLeft" size={13} />
            Recovery Center
          </Link>
        }
        title={
          <span className="row row-2 wrap">
            <span className="mono">Plan {plan.label}</span>
            <span>{plan.title}</span>
            {plan.recommended ? <RecommendedPill /> : null}
          </span>
        }
        subtitle={plan.summary}
        actions={
          <>
            <StatusChip kind="plan" value={plan.status} />
            <ProvenanceBadge value={plan.provenance} />
          </>
        }
      />

      <div className="stack stack-5">
        {plan.status === "executed" ? (
          <Banner tone="ontime" icon="CircleCheck" title="This plan has been executed">
            Every change is recorded with an honest state. Without a live booking provider these are
            recorded as requests or recorded offline — ReTryp does not claim a real ticket was
            rebooked.
          </Banner>
        ) : null}

        <div className="grid grid-4">
          <Card>
            <CardBody>
              <div className="eyebrow">Arrival impact</div>
              <div className="h3" style={{ marginTop: "var(--s-1)" }}>
                {plan.arrival_delta_display}
              </div>
              <div className="small muted">New arrival {plan.arrival_local}</div>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <div className="eyebrow">Total duration</div>
              <div className="h3" style={{ marginTop: "var(--s-1)" }}>
                {plan.total_duration_display}
              </div>
              <div className="small muted">End to end, door to hotel</div>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <div className="eyebrow">Additional cost</div>
              <div className="h3" style={{ marginTop: "var(--s-1)" }}>
                {plan.additional_cost_display}
              </div>
              <div className="small muted">
                {plan.refund_estimate_minor > 0
                  ? `${plan.refund_estimate_display} refund estimated`
                  : "No refund estimated"}
              </div>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <div className="eyebrow">Risk and connection</div>
              <div className="row row-2 wrap" style={{ marginTop: "var(--s-2)" }}>
                <StatusChip kind="risk" value={plan.risk_level} />
                <StatusChip kind="safety" value={plan.connection_safety} />
              </div>
            </CardBody>
          </Card>
        </div>

        {/* original vs recovered */}
        <Card>
          <CardHeader
            title="Original against recovered journey"
            subtitle="Side by side, with replacement segments called out"
            icon="Shuffle"
          />
          <CardBody>
            <div className="original-recovered">
              <div className="journey-column">
                <div className="journey-column__head">
                  <span className="h4">Original</span>
                  <Chip variant="done" icon="History">
                    As booked
                  </Chip>
                </div>
                <div className="list-rows">
                  {original_itinerary.map((segment) => (
                    <div key={segment.id} className="row row-3" style={{ padding: "var(--s-3) 0" }}>
                      <Icon name={modeIcon(segment.segment_type)} size={16} />
                      <div className="grow">
                        <div style={{ fontWeight: 500 }}>
                          {segment.carrier_name} {segment.service_number}
                        </div>
                        <div className="tiny muted">
                          {segment.origin.code} → {segment.destination.code} ·{" "}
                          {segment.effective_departure_local}
                        </div>
                      </div>
                      <StatusChip kind="segment" value={segment.status} size="sm" />
                    </div>
                  ))}
                </div>
              </div>

              <div className="divider-v" />

              <div className="journey-column">
                <div className="journey-column__head">
                  <span className="h4">Recovered</span>
                  <Chip variant="recovery" icon="RefreshCw">
                    Replacement legs
                  </Chip>
                </div>
                {recovered_itinerary.length === 0 ? (
                  <p className="small muted">No replacement legs. Existing transport is kept.</p>
                ) : (
                  <div className="list-rows">
                    {recovered_itinerary.map((segment) => (
                      <div key={segment.key} className="row row-3" style={{ padding: "var(--s-3) 0" }}>
                        <Icon name={modeIcon(segment.mode)} size={16} />
                        <div className="grow">
                          <div style={{ fontWeight: 500 }}>
                            {segment.carrier_name} {segment.service_number}
                          </div>
                          <div className="tiny muted">
                            {segment.origin_code} → {segment.destination_code} ·{" "}
                            {segment.departure_local}
                          </div>
                        </div>
                        <StatusChip kind="safety" value={segment.connection_safety} size="sm" />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </CardBody>
        </Card>

        {/* transport detail */}
        {plan.segments.length > 0 ? (
          <Card>
            <CardHeader title="Replacement segments" subtitle="Full timing and connection detail" icon="Plane" />
            <CardBody flush>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Service</th>
                      <th>Route</th>
                      <th>Departure</th>
                      <th>Arrival</th>
                      <th className="is-numeric">Duration</th>
                      <th>Connection</th>
                      <th className="is-numeric">Cost</th>
                      <th>Provenance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.segments.map((segment) => (
                      <tr key={segment.key}>
                        <td>
                          <div className="cell-primary">
                            {segment.carrier_name} {segment.service_number}
                          </div>
                          <div className="cell-sub">
                            {segment.fare_class ?? "—"} {segment.cabin ? `· ${segment.cabin}` : ""}
                          </div>
                        </td>
                        <td>
                          <div className="cell-primary">
                            {segment.origin_code} → {segment.destination_code}
                          </div>
                          <div className="cell-sub">
                            {segment.origin_name} to {segment.destination_name}
                          </div>
                        </td>
                        <td>
                          <div className="numeric">{clockFromLocal(segment.departure_local)}</div>
                          <div className="cell-sub">
                            {dateFromLocal(segment.departure_local)} ·{" "}
                            {zoneFromLocal(segment.departure_local)}
                          </div>
                        </td>
                        <td>
                          <div className="numeric">{clockFromLocal(segment.arrival_local)}</div>
                          <div className="cell-sub">
                            {dateFromLocal(segment.arrival_local)} ·{" "}
                            {zoneFromLocal(segment.arrival_local)}
                          </div>
                        </td>
                        <td className="is-numeric">{segment.duration_minutes} min</td>
                        <td>
                          <StatusChip kind="safety" value={segment.connection_safety} size="sm" />
                          {segment.buffer_minutes !== null && segment.required_minutes !== null ? (
                            <div className="cell-sub">
                              {segment.buffer_minutes} min buffer / {segment.required_minutes} min min
                            </div>
                          ) : null}
                        </td>
                        <td className="is-numeric">
                          {segment.currency} {(segment.cost_minor / 100).toFixed(2)}
                        </td>
                        <td>
                          <ProvenanceBadge value={segment.provenance} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardBody>
          </Card>
        ) : null}

        <div className="grid grid-2">
          {/* cost and compensation */}
          <Card>
            <CardHeader title="Cost and compensation" subtitle="Estimates from published rules" icon="Wallet" />
            <CardBody className="stack stack-5">
              <CostBreakdown
                additionalCost={plan.additional_cost_minor}
                refundEstimate={plan.refund_estimate_minor}
                currency={plan.currency}
              />
              <Divider />
              <CompensationCard estimate={plan.compensation} />
            </CardBody>
          </Card>

          {/* scoring */}
          <Card>
            <CardHeader title="How this plan scored" subtitle="Deterministic factors and weights" icon="Gauge" />
            <CardBody className="stack stack-5">
              <ScoreBreakdown plan={plan} />

              <Divider />

              <div>
                <div className="eyebrow" style={{ marginBottom: "var(--s-2)" }}>
                  Decision factors
                </div>
                <ul className="factor-list">
                  {plan.decision_factors.map((factor) => (
                    <li key={factor} className="factor">
                      <Icon name="Minus" size={12} />
                      <span>{factor}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {plan.restrictions.length > 0 ? (
                <>
                  <Divider />
                  <div>
                    <div className="eyebrow" style={{ marginBottom: "var(--s-2)" }}>
                      Restrictions
                    </div>
                    <ul className="factor-list">
                      {plan.restrictions.map((restriction) => (
                        <li key={restriction} className="factor">
                          <Icon name="Info" size={12} />
                          <span>{restriction}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </>
              ) : null}

              <Button variant="ghost" size="sm" icon="CircleHelp" onClick={() => setHelpOpen(true)}>
                Ask about this plan
              </Button>
            </CardBody>
          </Card>
        </div>

        {/* hotel and ground changes */}
        {plan.hotel_changes.length > 0 || plan.ground_transport.length > 0 ? (
          <Card>
            <CardHeader title="Hotel and ground changes" icon="BedDouble" />
            <CardBody>
              <div className="grid grid-2">
                {plan.hotel_changes.map((change) => (
                  <div key={`${change.hotel_id}-${change.action}`} className="card card--flat">
                    <CardBody tight>
                      <div className="row row-2 wrap" style={{ marginBottom: "var(--s-2)" }}>
                        <Icon name="BedDouble" size={16} />
                        <span className="h4">{change.name}</span>
                        <ProvenanceBadge value={change.provenance} />
                      </div>
                      <p className="small secondary">{change.detail}</p>
                      <MetricRow
                        label="Additional cost"
                        value={
                          change.cost_minor > 0
                            ? `${change.currency} ${(change.cost_minor / 100).toFixed(2)}`
                            : "None"
                        }
                      />
                    </CardBody>
                  </div>
                ))}
                {plan.ground_transport.map((item) => (
                  <div key={item.key} className="card card--flat">
                    <CardBody tight>
                      <div className="row row-2 wrap" style={{ marginBottom: "var(--s-2)" }}>
                        <Icon name="CarFront" size={16} />
                        <span className="h4">{item.provider_name}</span>
                        <ProvenanceBadge value={item.provenance} />
                      </div>
                      <p className="small secondary">
                        {item.from_label} → {item.to_label}
                      </p>
                      <MetricRow label="New pickup" value={item.pickup_local} />
                      <MetricRow
                        label="Cost"
                        value={`${item.currency} ${(item.cost_minor / 100).toFixed(2)}`}
                      />
                      {item.note ? <p className="tiny muted">{item.note}</p> : null}
                    </CardBody>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        ) : null}

        {/* map */}
        {dashboard.data ? (
          <Card>
            <CardHeader title="Route" subtitle="Original and recovered paths" icon="Map" />
            <CardBody tight>
              <TripMap
                segments={dashboard.data.trip.segments}
                hotels={dashboard.data.trip.hotels}
                ground={dashboard.data.trip.ground}
                plan={plan}
                currentPlaceCode={dashboard.data.trip.current_location?.place_code}
              />
            </CardBody>
          </Card>
        ) : null}

        {/* actions */}
        <Card>
          <CardHeader
            title="Execution"
            subtitle="Approval and execution are separate, deliberate steps"
            icon="ShieldCheck"
          />
          <CardBody className="stack stack-4">
            {plan.approved_at_utc ? (
              <Banner tone="ontime" icon="CircleCheck" title="Approved">
                Approved on {new Date(plan.approved_at_utc).toLocaleString("en-GB")}.
              </Banner>
            ) : null}

            {plan.actions.length > 0 ? (
              <div>
                <div className="eyebrow" style={{ marginBottom: "var(--s-2)" }}>
                  Action log
                </div>
                <div className="list-rows">
                  {plan.actions.map((action) => (
                    <div key={action.id} className="row row-4" style={{ padding: "var(--s-3) 0" }}>
                      <StatusChip kind="action" value={action.status} size="sm" />
                      <div className="grow">
                        <div className="small">{action.description}</div>
                        {action.result && typeof action.result.note === "string" ? (
                          <div className="tiny muted">{action.result.note}</div>
                        ) : null}
                      </div>
                      <span className="tiny muted numeric" style={{ flex: "none" }}>
                        {action.executed_at_utc
                          ? new Date(action.executed_at_utc).toLocaleString("en-GB")
                          : "Pending"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="small muted">
                No actions have been taken yet. Approve the plan, then request execution.
              </p>
            )}

            <div className="row row-2 wrap">
              <Button
                variant="primary"
                icon="CircleCheck"
                onClick={() => setConfirmOpen(true)}
                disabled={!canApprove}
              >
                {plan.status === "proposed" ? "Approve this plan" : "Already approved"}
              </Button>
              <Button
                icon="Send"
                loading={execute.isPending}
                onClick={() => execute.mutate()}
                disabled={!canExecute}
              >
                Request execution
              </Button>
              <Link to="/recovery" className="btn btn--ghost">
                <Icon name="ChevronLeft" size={14} />
                Back to plans
              </Link>
            </div>

            {!canApprove && !canExecute ? (
              <p className="inline-note">
                <Icon name="Info" size={13} />
                <span>
                  This plan is {plan.status_label.toLowerCase()}. Approve or execute a plan that is
                  still proposed.
                </span>
              </p>
            ) : null}
          </CardBody>
        </Card>

        {trip ? (
          <p className="tiny muted">
            Trip <span className="mono">{trip.reference}</span> · {trip.name} ·{" "}
            {trip.traveller_name}
          </p>
        ) : null}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => approve.mutate()}
        busy={approve.isPending}
        title={`Approve plan ${plan.label}`}
        confirmLabel="Approve this plan"
      >
        <div className="stack stack-4">
          <p className="secondary small">{plan.summary}</p>
          <div className="card card--flat">
            <CardBody tight>
              <MetricRow label="Arrival impact" value={plan.arrival_delta_display} />
              <MetricRow label="Additional cost" value={plan.additional_cost_display} />
              <MetricRow label="Changes" value={String(plan.changes_count)} />
            </CardBody>
          </div>
          <Banner tone="info" icon="ShieldCheck">
            Approving records your decision. It does not book anything until you request execution,
            and every action is written to the audit log.
          </Banner>
        </div>
      </ConfirmDialog>

      <HelpPanel
        open={helpOpen}
        onClose={() => setHelpOpen(false)}
        tripId={tripId}
        plan={plan as RecoveryPlan}
      />
    </>
  );
}
