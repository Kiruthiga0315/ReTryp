import { Icon } from "../ui/Icon";
import { RecommendedPill, StatusChip } from "../ui/Badge";
import { useSort, sortItems } from "../../hooks/useSort";
import { SortHeader } from "../ui/Form";
import type { ComparisonRow } from "../../api/types";

type Field =
  | "label"
  | "score"
  | "arrival"
  | "cost"
  | "duration"
  | "changes"
  | "risk"
  | "compensation";

/** Sortable side-by-side comparison of every feasible plan. */
export function ComparisonTable({ rows }: { rows: ComparisonRow[] }) {
  const { sort, toggle } = useSort<Field>("score", "desc");

  const comparators = {
    label: (a: ComparisonRow, b: ComparisonRow) => a.label.localeCompare(b.label),
    score: (a: ComparisonRow, b: ComparisonRow) => a.score - b.score,
    arrival: (a: ComparisonRow, b: ComparisonRow) =>
      a.arrival_delta_minutes - b.arrival_delta_minutes,
    cost: (a: ComparisonRow, b: ComparisonRow) =>
      a.additional_cost_minor - b.additional_cost_minor,
    duration: (a: ComparisonRow, b: ComparisonRow) =>
      a.total_duration_minutes ?? 0 - (b.total_duration_minutes ?? 0),
    changes: (a: ComparisonRow, b: ComparisonRow) => a.changes_count - b.changes_count,
    risk: (a: ComparisonRow, b: ComparisonRow) =>
      ["low", "medium", "high"].indexOf(a.risk_level) -
      ["low", "medium", "high"].indexOf(b.risk_level),
    compensation: (a: ComparisonRow, b: ComparisonRow) =>
      (a.compensation_amount_minor ?? 0) - (b.compensation_amount_minor ?? 0),
  };

  const sorted = sortItems(rows, sort, comparators);
  const bestCost = Math.min(...rows.map((row) => row.additional_cost_minor));
  const bestArrival = Math.min(...rows.map((row) => row.arrival_delta_minutes));
  const bestScore = Math.max(...rows.map((row) => row.score));

  return (
    <div className="table-wrap">
      <table className="table compare-table">
        <caption className="visually-hidden">
          Side-by-side comparison of every feasible recovery plan
        </caption>
        <thead>
          <tr>
            <SortHeader field="label" label="Plan" sort={sort} onSort={toggle} />
            <SortHeader field="score" label="Score" sort={sort} onSort={toggle} numeric />
            <SortHeader field="arrival" label="Arrival impact" sort={sort} onSort={toggle} />
            <SortHeader field="duration" label="Total duration" sort={sort} onSort={toggle} />
            <SortHeader field="cost" label="Additional cost" sort={sort} onSort={toggle} numeric />
            <SortHeader field="changes" label="Changes" sort={sort} onSort={toggle} numeric />
            <th>Connection</th>
            <SortHeader field="risk" label="Risk" sort={sort} onSort={toggle} />
            <th>Hotel</th>
            <th>Ground</th>
            <SortHeader field="compensation" label="Compensation" sort={sort} onSort={toggle} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.plan_id}>
              <td>
                <div className="row row-2">
                  <span className="mono" style={{ fontWeight: 700 }}>
                    {row.label}
                  </span>
                  <span className="cell-primary">{row.title}</span>
                </div>
                {row.recommended ? (
                  <div style={{ marginTop: 4 }}>
                    <RecommendedPill />
                  </div>
                ) : null}
              </td>
              <td className={`is-numeric ${row.score === bestScore ? "is-best" : ""}`}>
                {row.score.toFixed(1)}
              </td>
              <td className={row.arrival_delta_minutes === bestArrival ? "is-best" : ""}>
                {row.arrival_delta_display}
              </td>
              <td>{row.total_duration_display}</td>
              <td className={`is-numeric ${row.additional_cost_minor === bestCost ? "is-best" : ""}`}>
                {row.additional_cost_display}
              </td>
              <td className="is-numeric">{row.changes_count}</td>
              <td>
                <StatusChip kind="safety" value={row.connection_safety} />
              </td>
              <td>
                <StatusChip kind="risk" value={row.risk_level} />
              </td>
              <td className="small secondary">{row.hotel_summary}</td>
              <td className="small secondary">{row.ground_summary}</td>
              <td className="small">{row.compensation_display}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Per-factor breakdown, so the score is never a black box. */
export function ScoreBreakdown({ plan }: { plan: { score_breakdown: Record<string, number>; score: number } }) {
  const labels: Record<string, string> = {
    arrival: "Arrival time",
    total_time: "Total travel time",
    cost: "Additional cost",
    connection: "Connection feasibility",
    changes: "Number of changes",
    hotel_impact: "Hotel impact",
    ground: "Ground transport",
    preference: "Passenger preferences",
    visa: "Visa and transit",
  };
  const entries = Object.entries(plan.score_breakdown);

  return (
    <div className="stack stack-2">
      <div className="row-between">
        <span className="eyebrow">Weighted factors</span>
        <span className="row row-2 small">
          <Icon name="Gauge" size={13} />
          <strong>{plan.score.toFixed(1)}</strong>
          <span className="muted">/ 100</span>
        </span>
      </div>
      <div className="stack stack-2">
        {entries.map(([key, value]) => (
          <div key={key} className="row row-3">
            <span className="small secondary" style={{ width: 150, flex: "none" }}>
              {labels[key] ?? key}
            </span>
            <span className="progress grow" style={{ flex: "1 1 auto" }}>
              <span
                className="progress__bar"
                style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, display: "block" }}
              />
            </span>
            <span className="mono tiny muted" style={{ width: 38, textAlign: "right" }}>
              {(value * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
      <p className="inline-note">
        <Icon name="Info" size={13} />
        <span>
          Scores come from deterministic arithmetic on arrival, cost, timing, connections and
          constraints. They are not a prediction of anything.
        </span>
      </p>
    </div>
  );
}
