import { Icon } from "../ui/Icon";
import { Chip, ProvenanceBadge } from "../ui/Badge";
import { money } from "../../lib/format";
import type { CompensationEstimate } from "../../api/types";

const OUTCOME_COPY: Record<string, { tone: "ontime" | "risk" | "recovery" | "done"; label: string }> = {
  potential_eligibility: { tone: "ontime", label: "Potential eligibility" },
  possible_eligibility: { tone: "risk", label: "Possible eligibility" },
  care_only: { tone: "recovery", label: "Care entitlement only" },
  not_eligible: { tone: "done", label: "Not eligible" },
  unknown: { tone: "done", label: "Not assessed" },
};

const NOT_ELIGIBLE_OUTCOMES = new Set(["not_eligible", "unknown"]);

/** Compensation estimate. Always framed as potential eligibility, never a promise. */
export function CompensationCard({ estimate }: { estimate: CompensationEstimate }) {
  const copy = OUTCOME_COPY[estimate.outcome] ?? OUTCOME_COPY.unknown;

  return (
    <div className="stack stack-4">
      <div className="row-between wrap">
        <div className="row row-2">
          <Chip variant={copy.tone} icon={NOT_ELIGIBLE_OUTCOMES.has(estimate.outcome) ? "CircleSlash" : "CircleDollarSign"}>
            {copy.label}
          </Chip>
          <ProvenanceBadge value="REFERENCE" />
        </div>
        <span className="h3 numeric">
          {NOT_ELIGIBLE_OUTCOMES.has(estimate.outcome) ? "—" : estimate.amount_display}
        </span>
      </div>

      <dl className="kv">
        <dt>Regulation</dt>
        <dd>{estimate.regulation_reference}</dd>
        <dt>Basis</dt>
        <dd>{estimate.basis === "dgca" ? "DGCA CAR Section 3 Series M Part IV (India)" : "EU 261/2004"}</dd>
        <dt>Route distance</dt>
        <dd>{estimate.distance_km ? `${estimate.distance_km.toLocaleString("en-GB")} km` : "Not applicable"}</dd>
        <dt>Arrival delay</dt>
        <dd>{estimate.delay_minutes} min</dd>
        <dt>Last verified</dt>
        <dd>{estimate.last_verified}</dd>
      </dl>

      {estimate.factors.length > 0 ? (
        <div>
          <div className="eyebrow" style={{ marginBottom: "var(--s-2)" }}>
            Contributing factors
          </div>
          <ul className="factor-list">
            {estimate.factors.map((factor) => (
              <li key={factor} className="factor">
                <Icon name="Minus" size={12} />
                <span>{factor}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {estimate.care_entitlements.length > 0 ? (
        <div>
          <div className="eyebrow" style={{ marginBottom: "var(--s-2)" }}>
            Care entitlements
          </div>
          <ul className="factor-list">
            {estimate.care_entitlements.map((item) => (
              <li key={item} className="factor">
                <Icon name="CircleCheck" size={12} />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="inline-note">
        <Icon name="TriangleAlert" size={13} />
        <span>{estimate.disclaimer}</span>
      </div>

      <a
        className="row row-2 small"
        href={estimate.regulation_url}
        target="_blank"
        rel="noreferrer noopener"
      >
        <Icon name="ExternalLink" size={13} />
        Read the regulation text
      </a>
    </div>
  );
}

/** Refund versus additional cost, kept separate on purpose. */
export function CostBreakdown({
  additionalCost,
  refundEstimate,
  currency,
}: {
  additionalCost: number;
  refundEstimate: number;
  currency: string;
}) {
  return (
    <div className="stack stack-2">
      <div className="metric-row">
        <span className="metric-row__label">Additional cost</span>
        <span className="metric-row__value">{money(additionalCost, currency)}</span>
      </div>
      <div className="metric-row">
        <span className="metric-row__label">Refund estimate</span>
        <span className="metric-row__value">
          {refundEstimate > 0 ? money(refundEstimate, currency) : "Not estimated"}
        </span>
      </div>
      <div className="metric-row">
        <span className="metric-row__label">Compensation estimate</span>
        <span className="metric-row__value">See compensation panel</span>
      </div>
      <p className="inline-note">
        <Icon name="Info" size={13} />
        <span>
          Refunds and compensation are estimates from published rules. They are shown separately and
          are not guaranteed.
        </span>
      </p>
    </div>
  );
}
