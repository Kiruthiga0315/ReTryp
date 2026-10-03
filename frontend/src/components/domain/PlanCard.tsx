import { useState } from "react";
import { Link } from "react-router-dom";
import { Icon, modeIcon } from "../ui/Icon";
import { Chip, ProvenanceBadge, RecommendedPill, StatusChip } from "../ui/Badge";
import { Button } from "../ui/Button";
import { ScoreBar } from "../ui/States";
import { changesLabel, money } from "../../lib/format";
import type { RecoveryPlan } from "../../api/types";

const HOTEL_ACTION_LABEL: Record<string, string> = {
  keep: "Hotel retained",
  late_arrival_notice: "Late-arrival notice",
  shift_one_night: "Hotel shifted one night",
  book_extra_night: "Extra hotel night",
  cancel: "Hotel cancelled",
};

export function PlanCard({
  plan,
  onReview,
  onOpenHelp,
}: {
  plan: RecoveryPlan;
  onReview?: (plan: RecoveryPlan) => void;
  onOpenHelp?: (plan: RecoveryPlan) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isRecommended = plan.recommended;
  const visibleFactors = expanded ? plan.decision_factors : plan.decision_factors.slice(0, 3);

  return (
    <article
      className={`card card--interactive ${isRecommended ? "card--selected" : ""}`}
      style={{
        borderColor: isRecommended ? "var(--accent-600)" : "var(--border-strong)",
        borderWidth: isRecommended ? 2 : 1,
      }}
      aria-label={`Recovery plan ${plan.label}: ${plan.title}`}
    >
      <div 
        style={{ 
          padding: "var(--s-4) var(--s-5)",
          background: isRecommended ? "var(--accent-50)" : "var(--surface-card)",
          borderBottom: "1px solid var(--border-subtle)"
        }}
      >
        <div className="row-between">
          <div className="row row-3">
            <span style={{ fontSize: "var(--text-xl)", fontWeight: 700, fontFamily: "var(--font-display)" }}>
              {plan.label}
            </span>
            <div>
              <div className="h4">{plan.title}</div>
              <div className="secondary small">{plan.summary}</div>
            </div>
          </div>
          {isRecommended ? (
            <div style={{ background: "var(--accent-600)", color: "white", padding: "4px 8px", fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>
              Recommended
            </div>
          ) : null}
        </div>
      </div>

      <div className="card__body stack stack-6" style={{ padding: "var(--s-6) var(--s-5)" }}>
        {/* Boarding Pass Style Metrics */}
        <div className="grid grid-3" style={{ gap: "var(--s-4)" }}>
          <HeadlineMetric
            label="Arrival"
            value={plan.arrival_delta_display}
            detail={plan.arrival_local}
          />
          <HeadlineMetric
            label="Extra Cost"
            value={plan.additional_cost_display}
            detail={plan.refund_estimate_minor > 0 ? `${plan.refund_estimate_display} refund` : "No refund expected"}
          />
          <HeadlineMetric
            label="Duration"
            value={plan.total_duration_display}
            detail={changesLabel(plan.changes_count)}
          />
        </div>

        {plan.segments.length > 0 ? (
          <section>
            <div className="eyebrow" style={{ marginBottom: "var(--s-3)" }}>Transport</div>
            <div className="stack stack-4">
              {plan.segments.map((segment) => (
                <div key={segment.key} className="row row-4">
                  <Icon name={modeIcon(segment.mode)} size={22} className="secondary" />
                  <div className="grow">
                    <div style={{ fontSize: "var(--text-2xl)", fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.02em", lineHeight: 1.1 }}>
                      {segment.origin_code} <span style={{ color: "var(--text-muted)", fontWeight: 400, margin: "0 6px" }}>→</span> {segment.destination_code}
                    </div>
                    <div style={{ fontSize: "var(--text-md)", fontWeight: 600, color: "var(--text-primary)", marginTop: "var(--s-2)" }}>
                      {segment.carrier_name ?? ""} {segment.service_number ?? ""}
                    </div>
                    <div className="secondary numeric" style={{ marginTop: "4px", fontSize: "var(--text-md)" }}>
                      {segment.departure_local} → {segment.arrival_local} · {segment.duration_minutes} min
                    </div>
                  </div>
                  {segment.cost_minor > 0 && (
                    <div className="numeric" style={{ fontSize: "var(--text-lg)", fontWeight: 600 }}>
                      {money(segment.cost_minor, segment.currency)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        ) : (
          <div className="secondary" style={{ fontSize: "var(--text-md)" }}>Existing transport kept unchanged</div>
        )}

        {(plan.hotel_changes.length > 0 || plan.ground_transport.length > 0) && (
          <section>
            <div className="eyebrow" style={{ marginBottom: "var(--s-3)" }}>Accommodations & Ground</div>
            <div className="stack stack-4">
              {plan.hotel_changes.map((change) => (
                <div key={`${change.hotel_id}-${change.action}`} className="row row-4">
                  <Icon name="BedDouble" size={22} className="secondary" />
                  <div className="grow">
                    <div style={{ fontSize: "var(--text-2xl)", fontFamily: "var(--font-display)", fontWeight: 700, lineHeight: 1.1 }}>
                      {change.name}
                    </div>
                    <div style={{ fontSize: "var(--text-md)", fontWeight: 600, color: "var(--text-primary)", marginTop: "var(--s-2)" }}>
                      {HOTEL_ACTION_LABEL[change.action] ?? change.action}
                    </div>
                    <div className="secondary" style={{ marginTop: "4px", fontSize: "var(--text-md)" }}>{change.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      <div className="card__footer" style={{ background: "var(--surface-card)" }}>
        <div className="row row-2 wrap">
          {onOpenHelp && (
            <Button size="lg" variant="ghost" onClick={() => onOpenHelp(plan)}>
              Ask about this plan
            </Button>
          )}
          <Link to={`/recovery/plans/${plan.plan_id}`} className="btn btn--lg btn--ghost">
            View details
          </Link>
          {onReview && (
            <Button
              size="lg"
              variant={isRecommended ? "primary" : "default"}
              onClick={() => onReview(plan)}
            >
              Confirm Plan {plan.label}
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}

function HeadlineMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div>
      <div className="eyebrow" style={{ color: "var(--text-secondary)", marginBottom: "var(--s-1)" }}>{label}</div>
      <div className="numeric" style={{ fontWeight: 600, fontSize: "var(--text-2xl)", letterSpacing: "-0.02em" }}>{value}</div>
      <div className="secondary numeric" style={{ marginTop: "var(--s-1)", fontSize: "var(--text-md)" }}>{detail}</div>
    </div>
  );
}
