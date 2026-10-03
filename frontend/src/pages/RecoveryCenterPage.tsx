import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useCurrentTrip } from "../hooks/useTrip";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader, Banner, MetricRow, Divider } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { Chip, ProvenanceBadge, StatusChip } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState, SkeletonPage } from "../components/ui/States";
import { PlanCard } from "../components/domain/PlanCard";
import { ComparisonTable } from "../components/domain/ComparisonTable";
import { HelpPanel } from "../components/domain/HelpPanel";
import { useToast } from "../components/ui/Toast";
import { duration } from "../lib/format";
import type { RecoveryPlan, RecoveryPayload } from "../api/types";

export function RecoveryCenterPage() {
  const trip = useCurrentTrip();
  const queryClient = useQueryClient();
  const toast = useToast();

  const tripId = trip.data?.trip.id;
  const recovery = useQuery({
    queryKey: ["recovery", tripId],
    queryFn: () => api.recovery(tripId!),
    enabled: Boolean(tripId),
    refetchOnWindowFocus: true,
  });

  const monitoring = useQuery({
    queryKey: ["monitoring", tripId],
    queryFn: () => api.monitoring(tripId!),
    enabled: Boolean(tripId),
  });

  const [confirmPlan, setConfirmPlan] = useState<RecoveryPlan | null>(null);
  const [helpPlan, setHelpPlan] = useState<RecoveryPlan | null>(null);

  const approve = useMutation({
    mutationFn: (planId: string) => api.approvePlan(planId, true),
    onSuccess: (data) => {
      void queryClient.invalidateQueries();
      toast.success(
        `Plan ${data.plan.label} approved`,
        "The plan is confirmed. Execution can now be requested.",
      );
      setConfirmPlan(null);
    },
    onError: (error: Error) => toast.error("Could not approve the plan", error.message),
  });

  const execute = useMutation({
    mutationFn: (planId: string) => api.executePlan(planId),
    onSuccess: (data) => {
      void queryClient.invalidateQueries();
      const confirmed = data.plan.actions.filter((action) =>
        action.status === "confirmed" || action.status === "recorded_offline",
      ).length;
      toast.success(
        `Execution recorded for plan ${data.plan.label}`,
        confirmed > 0
          ? `${confirmed} ${confirmed === 1 ? "action" : "actions"} recorded. No live booking provider is configured.`
          : "Changes requested. No live booking provider is configured, so these are recorded as requests.",
      );
    },
    onError: (error: Error) => toast.error("Could not execute the plan", error.message),
  });

  const reject = useMutation({
    mutationFn: (planId: string) => api.rejectPlan(planId),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      toast.info("Plan rejected", "The plan has been set aside. Other plans remain available.");
    },
    onError: (error: Error) => toast.error("Could not reject the plan", error.message),
  });

  const checkMonitoring = useMutation({
    mutationFn: () => api.checkMonitoring(tripId!),
    onSuccess: (data) => {
      void queryClient.invalidateQueries();
      if (!data.healthy) {
        toast.warning("Monitoring found a problem", "A new recovery cycle has been started.");
      } else {
        toast.success("Monitoring check complete", "The active plan is still valid.");
      }
    },
    onError: (error: Error) => toast.error("Monitoring check failed", error.message),
  });

  // Derived before the early returns so hook order is stable across renders.
  const plans = recovery.data?.plans ?? [];
  const recommended = useMemo(
    () => plans.find((plan) => plan.recommended) ?? null,
    [plans],
  );
  const approvedPlan = useMemo(
    () => plans.find((plan) => plan.status === "approved") ?? null,
    [plans],
  );

  if (trip.isLoading || recovery.isLoading) return <SkeletonPage />;
  if (recovery.isError || !recovery.data) {
    return (
      <ErrorState
        title="Cannot load the Recovery Center"
        message={(recovery.error as Error)?.message ?? "No recovery data was returned."}
        onRetry={() => void recovery.refetch()}
      />
    );
  }

  const data = recovery.data;
  const activePlan = data.active_plan;

  return (
    <>
      <PageHeader
        title="Recovery Center"
        subtitle={
          data.disruption
            ? `Recovery cycle ${data.disruption.cycle} · ${data.disruption.kind_label}`
            : "No active disruption"
        }
        actions={
          <>
            {data.disruption ? (
              <StatusChip kind="disruption" value={data.disruption.status} />
            ) : (
              <Chip variant="ontime" icon="CircleCheck">
                Journey healthy
              </Chip>
            )}
            <Button
              size="sm"
              icon="Activity"
              loading={checkMonitoring.isPending}
              onClick={() => checkMonitoring.mutate()}
              disabled={!tripId}
            >
              Run monitoring check
            </Button>
          </>
        }
      />

      {!data.disruption ? (
        <Card>
          <EmptyState icon="CircleCheck" title="Nothing to recover right now">
            The journey is running to plan. When a segment breaks, the disruption appears here with
            complete recovery plans and a comparison of every option.
            <div className="row row-2" style={{ marginTop: "var(--s-3)", justifyContent: "center" }}>
              <Link to="/journey" className="btn btn--sm">
                <Icon name="Route" size={14} />
                View the journey
              </Link>
            </div>
          </EmptyState>
        </Card>
      ) : (
        <div className="stack stack-5">
          <DisruptionSummary data={data} />

          <ImpactPanel data={data} />

          {activePlan && activePlan.status === "executed" ? (
            <ExecutedPlanPanel plan={activePlan} monitoring={monitoring.data} />
          ) : null}

          {approvedPlan ? (
            <Card>
              <CardHeader
                title={`Plan ${approvedPlan.label} is approved`}
                subtitle="Approval is recorded. Request execution to log each change."
                icon="Send"
                actions={<StatusChip kind="plan" value={approvedPlan.status} />}
              />
              <CardBody>
                <p className="small secondary" style={{ marginBottom: "var(--s-3)" }}>
                  Execution writes one action per change to the audit log. Without a live booking
                  provider these are recorded as requests or recorded offline.
                </p>
                <div className="row row-2 wrap">
                  <Button
                    variant="primary"
                    icon="Send"
                    loading={execute.isPending}
                    onClick={() => execute.mutate(approvedPlan.plan_id)}
                  >
                    Request execution
                  </Button>
                  <Button
                    variant="ghost"
                    icon="CircleSlash"
                    loading={reject.isPending}
                    onClick={() => reject.mutate(approvedPlan.plan_id)}
                  >
                    Set this plan aside
                  </Button>
                  <Link to={`/recovery/plans/${approvedPlan.plan_id}`} className="btn btn--ghost">
                    <Icon name="Eye" size={13} />
                    Open plan detail
                  </Link>
                </div>
              </CardBody>
            </Card>
          ) : null}

          {/* plans */}
          <section aria-label="Recovery plans">
            <div className="row-between wrap" style={{ marginBottom: "var(--s-3)" }}>
              <div>
                <h2 className="h2">Recovery plans</h2>
                <p className="secondary small">
                  {plans.length} feasible {plans.length === 1 ? "plan" : "plans"} built from
                  available alternatives.{" "}
                  {recommended
                    ? `Plan ${recommended.label} is recommended on arrival time, cost and connection safety.`
                    : "No plan is recommended yet."}
                </p>
              </div>
            </div>

            {plans.length === 0 ? (
              <Card>
                <EmptyState icon="Route" title="No feasible plan could be built">
                  {data.empty_reason ??
                    "Every alternative conflicts with a constraint: connection times, visa rules, baggage or availability."}
                </EmptyState>
              </Card>
            ) : (
              <div className="grid grid-plans">
                {plans.map((plan) => (
                  <PlanCard
                    key={plan.plan_id}
                    plan={plan}
                    onReview={(selected) => setConfirmPlan(selected)}
                    onOpenHelp={(selected) => setHelpPlan(selected)}
                  />
                ))}
              </div>
            )}
          </section>

          {plans.length > 1 ? (
            <Card>
              <CardHeader
                title="Side-by-side comparison"
                subtitle="Sort by any column. The best value in each numeric column is highlighted."
                icon="ListFilter"
              />
              <CardBody flush>
                <ComparisonTable rows={data.comparison} />
              </CardBody>
            </Card>
          ) : null}

          {plans.length > 0 ? (
            <Card>
              <CardHeader title="Confirm a plan" subtitle="Execution is logged and idempotent" icon="ShieldCheck" />
              <CardBody>
                <p className="small secondary" style={{ marginBottom: "var(--s-3)" }}>
                  Approving a plan records the decision. Requesting execution then logs each change.
                  Without a live booking provider, changes are recorded as requests or recorded
                  offline — ReTryp never claims a real ticket was rebooked.
                </p>
                <div className="row row-2 wrap">
                  {plans.map((plan) => (
                    <Button
                      key={plan.plan_id}
                      size="sm"
                      variant={plan.recommended ? "primary" : "default"}
                      icon={plan.recommended ? "CircleCheck" : undefined}
                      onClick={() => setConfirmPlan(plan)}
                      disabled={plan.status === "executed"}
                    >
                      Review plan {plan.label}
                      {plan.recommended ? " (recommended)" : ""}
                    </Button>
                  ))}
                </div>
              </CardBody>
            </Card>
          ) : null}
        </div>
      )}

      <ConfirmDialog
        open={Boolean(confirmPlan)}
        onClose={() => setConfirmPlan(null)}
        onConfirm={() => confirmPlan && approve.mutate(confirmPlan.plan_id)}
        busy={approve.isPending}
        title={confirmPlan ? `Confirm plan ${confirmPlan.label}: ${confirmPlan.title}` : "Confirm plan"}
        confirmLabel="Approve this plan"
      >
        {confirmPlan ? (
          <div className="stack stack-4">
            <p className="secondary small">{confirmPlan.summary}</p>

            <div className="card card--flat">
              <CardBody tight>
                <MetricRow label="Arrival impact" value={confirmPlan.arrival_delta_display} />
                <MetricRow label="Total duration" value={confirmPlan.total_duration_display} />
                <MetricRow label="Additional cost" value={confirmPlan.additional_cost_display} />
                <MetricRow label="Refund estimate" value={confirmPlan.refund_estimate_display} />
                <MetricRow label="Changes" value={String(confirmPlan.changes_count)} />
              </CardBody>
            </div>

            {confirmPlan.segments.length > 0 ? (
              <div>
                <div className="eyebrow" style={{ marginBottom: "var(--s-2)" }}>
                  Replacement transport
                </div>
                <div className="list-rows">
                  {confirmPlan.segments.map((segment) => (
                    <div key={segment.key} className="row-between small">
                      <span>
                        {segment.carrier_name} {segment.service_number} · {segment.origin_code} →{" "}
                        {segment.destination_code}
                      </span>
                      <span className="mono muted">{segment.arrival_local}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {confirmPlan.restrictions.length > 0 ? (
              <div>
                <div className="eyebrow" style={{ marginBottom: "var(--s-2)" }}>
                  Restrictions
                </div>
                <ul className="factor-list">
                  {confirmPlan.restrictions.map((restriction) => (
                    <li key={restriction} className="factor">
                      <Icon name="Info" size={12} />
                      <span>{restriction}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Banner tone="info" icon="ShieldCheck">
              Approving does not book anything by itself. You will be able to request execution next,
              and every action is written to the audit log.
            </Banner>
          </div>
        ) : null}
      </ConfirmDialog>

      <HelpPanel
        open={Boolean(helpPlan)}
        onClose={() => setHelpPlan(null)}
        tripId={tripId ?? null}
        plan={helpPlan}
      />
    </>
  );
}

function DisruptionSummary({ data }: { data: RecoveryPayload }) {
  const disruption = data.disruption!;
  const impact = data.impact;

  return (
    <Card>
      <CardHeader
        title={disruption.title}
        subtitle={`${disruption.kind_label} · detected ${new Date(disruption.detected_at_utc).toLocaleString("en-GB")}`}
        icon="TriangleAlert"
        actions={
          <>
            <StatusChip kind="severity" value={disruption.severity} />
            <ProvenanceBadge value={disruption.provenance} />
          </>
        }
      />
      <CardBody>
        <p className="secondary" style={{ marginBottom: "var(--s-4)" }}>
          {disruption.detail}
        </p>

        <div className="grid grid-3">
          <div>
            <div className="eyebrow">Severity</div>
            <div style={{ marginTop: "var(--s-2)" }}>
              <StatusChip kind="severity" value={disruption.severity} />
            </div>
          </div>
          <div>
            <div className="eyebrow">Connection status</div>
            <div style={{ marginTop: "var(--s-2)" }}>
              <StatusChip kind="safety" value={impact?.connection_safety ?? "safe"} />
            </div>
          </div>
          <div>
            <div className="eyebrow">Final arrival shift</div>
            <div style={{ marginTop: "var(--s-2)", fontWeight: 600 }}>
              {impact && impact.final_arrival_shift_minutes !== 0
                ? `${impact.final_arrival_shift_minutes > 0 ? "+" : "−"}${duration(Math.abs(impact.final_arrival_shift_minutes))}`
                : "No change"}
            </div>
          </div>
        </div>

        <Divider />

        <div className="row row-2 wrap" style={{ marginTop: "var(--s-4)" }}>
          {disruption.delay_display ? (
            <span className="tag">
              <Icon name="Clock" size={11} />
              Delay {disruption.delay_display}
            </span>
          ) : null}
          <span className="tag">Recovery cycle {disruption.cycle}</span>
          <span className="tag">
            <Icon name="History" size={11} />
            {disruption.source ?? "Unknown source"}
          </span>
        </div>
      </CardBody>
    </Card>
  );
}

function ImpactPanel({ data }: { data: RecoveryPayload }) {
  const impact = data.impact;
  if (!impact || impact.items.length === 0) return null;

  return (
    <Card>
      <CardHeader
        title="Itinerary impact"
        subtitle="Cascading consequences traced across the whole journey"
        icon="Activity"
        actions={<span className="tag">{impact.items.length} effects</span>}
      />
      <CardBody flush>
        <div className="list-rows">
          {impact.items.map((item, index) => (
            <div key={`${item.kind}-${index}`} className="row row-4" style={{ padding: "var(--s-4) var(--s-5)" }}>
              <div style={{ flex: "none", paddingTop: 2 }}>
                <StatusChip kind="severity" value={item.severity} size="sm" />
              </div>
              <div className="grow">
                <div style={{ fontWeight: 500 }}>{item.title}</div>
                <div className="small muted" style={{ marginTop: 2 }}>
                  {item.detail}
                </div>
              </div>
              {item.delta_display ? (
                <span className="tag" style={{ flex: "none" }}>
                  {item.delta_display}
                </span>
              ) : null}
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function ExecutedPlanPanel({
  plan,
  monitoring,
}: {
  plan: RecoveryPlan;
  monitoring: { watching: boolean; cycle: number; last_result: Record<string, unknown> | null } | undefined;
}) {
  const confirmed = plan.actions.filter(
    (action) => action.status === "confirmed" || action.status === "recorded_offline",
  );
  const requested = plan.actions.filter((action) => action.status === "requested" || action.status === "pending_provider");

  return (
    <Card>
      <CardHeader
        title={`Plan ${plan.label} is executing`}
        subtitle="Each change is logged with an honest state"
        icon="ShieldCheck"
        actions={
          <>
            <StatusChip kind="plan" value={plan.status} />
            <ProvenanceBadge value={plan.provenance} />
          </>
        }
      />
      <CardBody flush>
        <div className="list-rows">
          {plan.actions.map((action) => (
            <div key={action.id} className="row row-4" style={{ padding: "var(--s-3) var(--s-5)" }}>
              <StatusChip kind="action" value={action.status} size="sm" />
              <div className="grow">
                <div className="small">{action.description}</div>
                {action.result && typeof action.result.note === "string" ? (
                  <div className="tiny muted">{action.result.note}</div>
                ) : null}
              </div>
              <span className="tiny muted numeric" style={{ flex: "none" }}>
                {action.executed_at_utc
                  ? new Date(action.executed_at_utc).toLocaleTimeString("en-GB", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "Pending"}
              </span>
            </div>
          ))}
        </div>
      </CardBody>
      <div className="card__footer">
        <div className="row row-2 wrap">
          {confirmed.length > 0 ? (
            <Chip variant="recovery" icon="CircleCheck">
              {confirmed.length} recorded
            </Chip>
          ) : null}
          {requested.length > 0 ? (
            <Chip variant="risk" icon="Clock">
              {requested.length} pending provider confirmation
            </Chip>
          ) : null}
          {monitoring ? (
            <span className="tag">
              <Icon name="Activity" size={11} />
              Monitoring {monitoring.watching ? "active" : "paused"} · cycle {monitoring.cycle}
            </span>
          ) : null}
        </div>
        <Link to={`/recovery/plans/${plan.plan_id}`} className="btn btn--sm">
          <Icon name="Eye" size={13} />
          Open plan detail
        </Link>
      </div>
    </Card>
  );
}
