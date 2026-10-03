import { Icon, modeIcon } from "../ui/Icon";
import { Chip, ProvenanceBadge, StatusChip } from "../ui/Badge";
import { Card, CardBody } from "../ui/Card";
import { duration, zoneFromLocal, clockFromLocal, dateFromLocal } from "../../lib/format";
import type { Segment } from "../../api/types";

function dotVariant(status: string): string {
  switch (status) {
    case "cancelled":
    case "missed":
    case "diverted":
      return "disrupted";
    case "delayed":
    case "at_risk":
      return "risk";
    case "recovered":
    case "departed":
    case "in_progress":
    case "boarding":
      return "recovery";
    case "completed":
    case "arrived":
      return "done";
    default:
      return "ontime";
  }
}

/** One leg of the journey, as a timeline entry with scheduled versus updated times. */
export function SegmentTimelineItem({
  segment,
  isLast,
  connectionNote,
}: {
  segment: Segment;
  isLast: boolean;
  connectionNote?: { bufferMinutes: number; requiredMinutes: number; safety: string; note: string } | null;
}) {
  const changed =
    segment.effective_departure_local !== segment.scheduled_departure_local ||
    segment.effective_arrival_local !== segment.scheduled_arrival_local;

  return (
    <li className="timeline__item">
      <div className="timeline__rail">
        <span className={`timeline__dot timeline__dot--${dotVariant(segment.status)}`}>
          <Icon name={modeIcon(segment.segment_type)} size={14} />
        </span>
        {!isLast ? <span className="timeline__line" /> : null}
      </div>

      <div className="timeline__content">
        <Card flat className="card--flat">
          <CardBody>
            <div className="segment-head">
              <div>
                <div className="row row-2 wrap">
                  <span className="h4">
                    {segment.carrier_name ?? segment.mode_label}{" "}
                    {segment.service_number ?? ""}
                  </span>
                  <StatusChip kind="segment" value={segment.status} />
                  {segment.is_recovery ? (
                    <Chip variant="recovery" icon="RefreshCw">
                      Replacement
                    </Chip>
                  ) : null}
                  <ProvenanceBadge value={segment.provenance} fetchedAt={segment.fetched_at} />
                </div>
                <div className="secondary small" style={{ marginTop: 2 }}>
                  {segment.origin.city} ({segment.origin.code}) to {segment.destination.city} (
                  {segment.destination.code}) · {segment.mode_label}
                </div>
              </div>
              {segment.booking_reference ? (
                <span className="tag" title="Booking reference">
                  <Icon name="Ticket" size={12} />
                  <span className="mono">{segment.booking_reference}</span>
                </span>
              ) : null}
            </div>

            <div className="segment-times">
              <div className="segment-time">
                <div className="segment-time__label">Departure · {zoneFromLocal(segment.effective_departure_local)}</div>
                <div className={`segment-time__value ${changed ? "segment-time__value--changed" : ""}`}>
                  {clockFromLocal(segment.effective_departure_local)}
                </div>
                <div className="tiny muted">{dateFromLocal(segment.effective_departure_local)}</div>
                {changed ? (
                  <div className="segment-time__was">
                    was {clockFromLocal(segment.scheduled_departure_local)}
                  </div>
                ) : null}
              </div>

              <span className="segment-arrow">
                <Icon name="ArrowRight" size={16} />
              </span>

              <div className="segment-time">
                <div className="segment-time__label">Arrival · {zoneFromLocal(segment.effective_arrival_local)}</div>
                <div className={`segment-time__value ${changed ? "segment-time__value--changed" : ""}`}>
                  {clockFromLocal(segment.effective_arrival_local)}
                </div>
                <div className="tiny muted">{dateFromLocal(segment.effective_arrival_local)}</div>
                {changed ? (
                  <div className="segment-time__was">
                    was {clockFromLocal(segment.scheduled_arrival_local)}
                  </div>
                ) : null}
              </div>

              <span className="segment-arrow">
                <Icon name="Timer" size={16} />
              </span>

              <div className="segment-time">
                <div className="segment-time__label">Duration</div>
                <div className="segment-time__value">{segment.duration_display}</div>
                {segment.arrival_delay_minutes > 0 ? (
                  <div className="tiny" style={{ color: "var(--status-risk)" }}>
                    {duration(segment.arrival_delay_minutes)} behind schedule
                  </div>
                ) : segment.status === "cancelled" ? (
                  <div className="tiny muted">Not operating</div>
                ) : segment.status === "missed" ? (
                  <div className="tiny muted">Missed at connection</div>
                ) : (
                  <div className="tiny muted">On schedule</div>
                )}
              </div>
            </div>

            <div className="segment-meta">
              {segment.terminal ? (
                <MetaItem label="Terminal" value={segment.terminal} />
              ) : null}
              {segment.gate ? <MetaItem label="Gate" value={segment.gate} /> : null}
              {segment.platform ? <MetaItem label="Platform" value={segment.platform} /> : null}
              {segment.cabin ? <MetaItem label="Cabin" value={segment.cabin} /> : null}
              {segment.fare_class ? <MetaItem label="Fare class" value={segment.fare_class} /> : null}
              {segment.distance_km ? (
                <MetaItem label="Distance" value={`${Math.round(segment.distance_km).toLocaleString("en-GB")} km`} />
              ) : null}
              {segment.cost_minor !== null && segment.cost_currency ? (
                <MetaItem
                  label="Booked cost"
                  value={`${segment.cost_currency} ${(segment.cost_minor / 100).toFixed(2)}`}
                />
              ) : null}
            </div>

            {connectionNote ? (
              <div style={{ marginTop: "var(--s-3)" }}>
                <ConnectionNote {...connectionNote} />
              </div>
            ) : null}
          </CardBody>
        </Card>
      </div>
    </li>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="meta-item">
      <div className="meta-item__label">{label}</div>
      <div className="meta-item__value">{value}</div>
    </div>
  );
}

export function ConnectionNote({
  bufferMinutes,
  requiredMinutes,
  safety,
  note,
}: {
  bufferMinutes: number;
  requiredMinutes: number;
  safety: string;
  note: string;
}) {
  const variant = safety === "safe" ? "ontime" : safety === "broken" ? "disrupted" : "risk";
  const label =
    safety === "safe"
      ? "Connection maintained"
      : safety === "tight"
        ? "Connection is tight"
        : "Connection at risk";
  return (
    <div className={`banner banner--${variant}`} style={{ padding: "var(--s-2) var(--s-3)" }}>
      <Icon name={safety === "safe" ? "CircleCheck" : "Clock"} size={15} />
      <div className="grow">
        <div className="row row-2 wrap">
          <strong>{label}</strong>
          <span className="tiny">
            {bufferMinutes >= 0 ? `${bufferMinutes} min buffer` : `${Math.abs(bufferMinutes)} min short`}{" "}
            · {requiredMinutes} min minimum
          </span>
        </div>
        {note ? <div className="tiny" style={{ opacity: 0.85 }}>{note}</div> : null}
      </div>
    </div>
  );
}
