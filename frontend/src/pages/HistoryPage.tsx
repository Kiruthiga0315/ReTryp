import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { useCurrentTrip } from "../hooks/useTrip";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader, MetricRow, Banner } from "../components/ui/Card";
import { Icon } from "../components/ui/Icon";
import { ProvenanceBadge, StatusChip, Chip } from "../components/ui/Badge";
import { EmptyState, ErrorState, SkeletonPage } from "../components/ui/States";
import type { AuditEntry } from "../api/types";

export function HistoryPage() {
  const { user } = useAuth();
  const trip = useCurrentTrip();
  const tripId = trip.data?.trip.id;

  const history = useQuery({
    queryKey: ["history", tripId],
    queryFn: () => api.history(tripId!),
    enabled: Boolean(tripId),
  });

  const canAudit = user?.role === "travel_manager" || user?.role === "admin";
  const audit = useQuery({
    queryKey: ["audit", tripId],
    queryFn: () => api.audit({ trip_id: tripId!, limit: 100 }),
    enabled: Boolean(tripId) && canAudit,
  });

  if (trip.isLoading || history.isLoading) return <SkeletonPage />;
  if (history.isError || !history.data) {
    return (
      <ErrorState
        title="Cannot load trip history"
        message={(history.error as Error)?.message ?? "No history was returned."}
        onRetry={() => void history.refetch()}
      />
    );
  }

  const data = history.data;
  const resolved = data.disruptions.filter((disruption) => disruption.status === "resolved");
  const executedPlans = data.plans.filter((plan) => plan.status === "executed");

  return (
    <>
      <PageHeader
        title="Trip History"
        subtitle={`${data.trip.name} · ${data.trip.reference}`}
        actions={
          <>
            <StatusChip kind="trip" value={data.trip.status} />
            <ProvenanceBadge value={data.trip.provenance} />
          </>
        }
      />

      <div className="stack stack-5">
        <div className="grid grid-4">
          <Card>
            <CardBody>
              <div className="eyebrow">Disruptions</div>
              <div className="h2" style={{ marginTop: "var(--s-1)" }}>
                {data.disruptions.length}
              </div>
              <div className="small muted">{resolved.length} resolved</div>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <div className="eyebrow">Recoveries performed</div>
              <div className="h2" style={{ marginTop: "var(--s-1)" }}>
                {data.recovery_performed}
              </div>
              <div className="small muted">{executedPlans.length} executed plans</div>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <div className="eyebrow">Extra cost</div>
              <div className="h2" style={{ marginTop: "var(--s-1)" }}>
                {data.extra_cost_display}
              </div>
              <div className="small muted">Additional cost across recoveries</div>
            </CardBody>
          </Card>
          <Card>
            <CardBody>
              <div className="eyebrow">Refunds</div>
              <div className="h2" style={{ marginTop: "var(--s-1)" }}>
                {data.refund_display}
              </div>
              <div className="small muted">Estimates only</div>
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader
            title="Disruption and recovery log"
            subtitle="Every disruption on this trip and the plan that resolved it"
            icon="History"
          />
          <CardBody flush>
            {data.disruptions.length === 0 ? (
              <EmptyState icon="CircleCheck" title="No disruptions recorded">
                This journey has run to plan from the start.
              </EmptyState>
            ) : (
              <div className="list-rows">
                {data.disruptions.map((disruption) => {
                  const plan = data.plans.find((candidate) => candidate.disruption_id === disruption.id);
                  return (
                    <div key={disruption.id} style={{ padding: "var(--s-4) var(--s-5)" }}>
                      <div className="row-between wrap">
                        <div className="grow">
                          <div className="row row-2 wrap">
                            <span className="h4">{disruption.title}</span>
                            <StatusChip kind="severity" value={disruption.severity} size="sm" />
                            <StatusChip kind="disruption" value={disruption.status} size="sm" />
                            <span className="tag">Cycle {disruption.cycle}</span>
                            <ProvenanceBadge value={disruption.provenance} />
                          </div>
                          <p className="small secondary" style={{ marginTop: "var(--s-1)" }}>
                            {disruption.detail}
                          </p>
                          <div className="tiny muted" style={{ marginTop: "var(--s-1)" }}>
                            Detected {new Date(disruption.detected_at_utc).toLocaleString("en-GB")}
                            {disruption.resolved_at_utc
                              ? ` · resolved ${new Date(disruption.resolved_at_utc).toLocaleString("en-GB")}`
                              : " · unresolved"}
                          </div>
                        </div>
                        {disruption.delay_display ? (
                          <span className="tag" style={{ flex: "none" }}>
                            <Icon name="Clock" size={11} />
                            {disruption.delay_display}
                          </span>
                        ) : null}
                      </div>

                      {plan ? (
                        <div
                          className="card card--flat"
                          style={{ marginTop: "var(--s-3)", background: "var(--surface-sunken)" }}
                        >
                          <CardBody tight>
                            <div className="row-between wrap">
                              <div>
                                <div className="row row-2">
                                  <span className="mono" style={{ fontWeight: 700 }}>
                                    {plan.label}
                                  </span>
                                  <span style={{ fontWeight: 500 }}>{plan.title}</span>
                                  <StatusChip kind="plan" value={plan.status} size="sm" />
                                </div>
                                <div className="tiny muted" style={{ marginTop: 2 }}>
                                  {plan.summary}
                                </div>
                              </div>
                              <Link to={`/recovery/plans/${plan.plan_id}`} className="btn btn--sm btn--ghost">
                                <Icon name="Eye" size={13} />
                                Plan detail
                              </Link>
                            </div>
                            <div className="grid grid-4" style={{ marginTop: "var(--s-3)" }}>
                              <div>
                                <div className="eyebrow">Arrival</div>
                                <div className="small">{plan.arrival_delta_display}</div>
                              </div>
                              <div>
                                <div className="eyebrow">Extra cost</div>
                                <div className="small">{plan.additional_cost_display}</div>
                              </div>
                              <div>
                                <div className="eyebrow">Compensation</div>
                                <div className="small">{plan.compensation.amount_display}</div>
                              </div>
                              <div>
                                <div className="eyebrow">Changes</div>
                                <div className="small">{plan.changes_count}</div>
                              </div>
                            </div>
                          </CardBody>
                        </div>
                      ) : (
                        <p className="tiny muted" style={{ marginTop: "var(--s-2)" }}>
                          No plan was selected for this disruption.
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </CardBody>
          <div className="card__footer">
            <MetricRow
              label="Final arrival"
              value={
                data.final_arrival_utc
                  ? new Date(data.final_arrival_utc).toLocaleString("en-GB")
                  : "Not yet arrived"
              }
            />
            <span className="tiny muted">All amounts are estimates from published rules.</span>
          </div>
        </Card>

        {canAudit ? (
          <Card>
            <CardHeader
              title="Audit log"
              subtitle="Events detected, plans generated, decisions taken, by whom and when"
              icon="ShieldCheck"
              actions={<Chip variant="info" icon="Users">Visible to managers and administrators</Chip>}
            />
            <CardBody flush>
              {audit.isLoading ? (
                <p className="small muted" style={{ padding: "var(--s-5)" }}>
                  Loading audit entries…
                </p>
              ) : audit.isError ? (
                <p className="small muted" style={{ padding: "var(--s-5)" }}>
                  Audit entries are not available.
                </p>
              ) : (audit.data?.entries.length ?? 0) === 0 ? (
                <EmptyState icon="ShieldCheck" title="No audit entries yet" />
              ) : (
                <div>
                  {audit.data!.entries.map((entry) => (
                    <AuditRow key={entry.id} entry={entry} />
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        ) : (
          <Banner tone="info" icon="Lock" title="Audit log is restricted">
            The audit log is visible to Travel Managers and Administrators. Your role does not permit
            access to it.
          </Banner>
        )}
      </div>
    </>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  return (
    <div className="audit-row">
      <div className="audit-row__time">
        {new Date(entry.created_at_utc).toLocaleString("en-GB")}
        <div className="tiny muted">{entry.created_at_local}</div>
      </div>
      <div>
        <div className="row row-2 wrap">
          <span style={{ fontWeight: 500 }}>{entry.summary}</span>
          <span className="tag">{entry.action_label}</span>
          <ProvenanceBadge value={entry.provenance} />
        </div>
        <div className="tiny muted" style={{ marginTop: 2 }}>
          {entry.actor_name} · {entry.actor_role}
          {entry.subject_kind ? ` · ${entry.subject_kind}` : ""}
        </div>
      </div>
    </div>
  );
}
