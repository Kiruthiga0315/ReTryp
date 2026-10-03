import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type {
  JourneyCoverage,
  JourneyItinerary,
  JourneyOption,
  JourneyPlace,
  JourneySelection,
} from "../api/types";
import { PageHeader } from "../components/layout/AppShell";
import { Banner, Card, CardBody, CardHeader, Stat } from "../components/ui/Card";
import { Button, IconButton } from "../components/ui/Button";
import { SelectField, TextField } from "../components/ui/Form";
import { Icon, modeIcon } from "../components/ui/Icon";
import { Chip, ModeIcon, ProvenanceBadge } from "../components/ui/Badge";
import { EmptyState, InlineNote, Skeleton } from "../components/ui/States";
import { PlacePicker } from "../components/domain/PlacePicker";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../hooks/useAuth";
import { displayCurrencyFor } from "../lib/format";

const DISRUPTION_KINDS = [
  { value: "flight_delay", label: "Delay" },
  { value: "flight_cancellation", label: "Cancellation" },
  { value: "missed_connection", label: "Missed connection" },
  { value: "ground_transport_disruption", label: "Ground transport disruption" },
];

function todayIso(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function legKey(from: JourneyPlace, to: JourneyPlace): string {
  return `${from.code}-${to.code}`;
}

export function JourneyBuilderPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { user } = useAuth();

  const [name, setName] = useState("");
  const [reason, setReason] = useState("business");
  const [origin, setOrigin] = useState<JourneyPlace | null>(null);
  const [destination, setDestination] = useState<JourneyPlace | null>(null);
  const [stops, setStops] = useState<JourneyPlace[]>([]);
  const [date, setDate] = useState(todayIso);
  const [selections, setSelections] = useState<Record<string, JourneyOption>>({});
  const [legDates, setLegDates] = useState<Record<string, string>>({});

  const [checkDisruption, setCheckDisruption] = useState(false);
  const [disruptionKind, setDisruptionKind] = useState("flight_delay");
  const [disruptedLegKey, setDisruptedLegKey] = useState("");
  const [delayMinutes, setDelayMinutes] = useState(225);

  const reasons = useQuery({
    queryKey: ["journey-reasons"],
    queryFn: api.journeyReasons,
    staleTime: 60 * 60 * 1000,
  });

  // The ordered chain of places becomes consecutive legs.
  const chain = useMemo(
    () => [origin, ...stops, destination].filter((p): p is JourneyPlace => p !== null),
    [origin, stops, destination],
  );

  const legs = useMemo(() => {
    const out: { from: JourneyPlace; to: JourneyPlace; key: string; date: string }[] = [];
    for (let i = 0; i + 1 < chain.length; i += 1) {
      const from = chain[i];
      const to = chain[i + 1];
      const key = legKey(from, to);
      out.push({ from, to, key, date: legDates[key] ?? date });
    }
    return out;
  }, [chain, legDates, date]);

  function dropSelection(key: string) {
    setSelections((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function choose(legId: string, option: JourneyOption | null) {
    if (!option) {
      dropSelection(legId);
      return;
    }
    setSelections((current) => ({ ...current, [legId]: option }));
    if (!disruptedLegKey) setDisruptedLegKey(legId);
  }

  const readiness = useMemo(() => {
    const problems: string[] = [];
    if (!name.trim()) problems.push("Trip name is required.");
    if (!origin) problems.push("Choose an origin.");
    if (!destination) problems.push("Choose a destination.");
    if (legs.length === 0) problems.push("Choose both ends to build the journey.");
    const missing = legs.filter((leg) => !selections[leg.key]);
    if (legs.length > 0 && missing.length > 0) {
      problems.push(
        `Select a service for ${missing.length} leg${missing.length > 1 ? "s" : ""}.`,
      );
    }
    return problems;
  }, [name, origin, destination, legs, selections]);

  const build = useMutation({
    mutationFn: () => {
      const payload: JourneySelection[] = legs.map((leg) => ({
        service_key: selections[leg.key].key,
        origin: leg.from.code,
        destination: leg.to.code,
        date: leg.date,
        mode: selections[leg.key].mode,
      }));
      const disrupted = checkDisruption && disruptedLegKey && selections[disruptedLegKey]
        ? selections[disruptedLegKey]
        : null;
      return api.buildJourney({
        name: name.trim(),
        reason,
        origin: origin!.code,
        destination: destination!.code,
        date,
        segments: payload,
        disrupted_service_key: disrupted?.key ?? null,
        disruption_kind: disrupted ? disruptionKind : null,
        delay_minutes: disrupted ? delayMinutes : 0,
      });
    },
    onSuccess: (result) => {
      if (result.cycle !== null) {
        toast.success("Recovery cycle opened", `${result.plans.length} plans ready to review.`);
        navigate("/recovery");
      } else {
        if (result.check.healthy) {
          toast.success("Journey built", "Connections check out.");
        } else {
          toast.warning("Journey built", "Issues found. Open the journey to review.");
        }
        navigate(`/map?trip=${result.trip.id}`);
      }
    },
  });

  const totalCost = Object.values(selections).reduce(
    (sum, option) => sum + option.cost_minor,
    0,
  );
  const currency =
    Object.values(selections)[0]?.cost_currency ?? displayCurrencyFor(user);

  return (
    <div className="stack-5">
      <PageHeader
        title="Journey builder"
        subtitle="Choose the places, review the services the data can answer for, then build and check the journey."
      />

      <Banner tone="info" icon="Database">
        Options are badged by provenance. Trains come from the published DELFI/GTFS.de timetable;
        flights come from the configured schedule provider. Nothing here is presented as a live
        feed unless a provider answered for it.
      </Banner>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) 320px", alignItems: "start" }}>
        <div className="stack-4">
          <Card>
            <CardHeader title="Trip" subtitle="Name it, say why, and set the departure day." icon="Route" />
            <CardBody className="stack-3">
              <div className="grid-2">
                <TextField
                  label="Trip name"
                  value={name}
                  onChange={setName}
                  placeholder="Germany Business Trip"
                  required
                />
                <SelectField
                  label="Reason for travel"
                  value={reason}
                  onChange={setReason}
                  options={(reasons.data?.reasons ?? []).map((r) => ({ value: r.code, label: r.label }))}
                />
              </div>
              <div className="grid-2">
                <TextField
                  label="Departure day"
                  type="date"
                  value={date}
                  onChange={(value) => {
                    setDate(value);
                    setLegDates({});
                  }}
                />
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Route" subtitle="Origin, any stops, and the destination." icon="MapPin" />
            <CardBody className="stack-3">
              <div className="grid-2">
                <PlacePicker label="Origin" value={origin} onChange={setOrigin} />
                <PlacePicker label="Destination" value={destination} onChange={setDestination} />
              </div>

              {stops.length > 0 ? (
                <div className="stack-2">
                  <div className="tiny muted">Stops</div>
                  {stops.map((stop, index) => (
                    <div key={stop.code} className="row-between row-emphasis">
                      <div className="row row-2">
                        <Icon name="MapPin" size={14} />
                        <span>
                          <strong>{stop.code}</strong> {stop.name}
                        </span>
                      </div>
                      <IconButton
                        icon="Trash2"
                        label={`Remove stop ${stop.code}`}
                        onClick={() => {
                          const removed = stops[index];
                          setStops(stops.filter((_, i) => i !== index));
                          dropSelection(legKey(chain[0] ?? removed, removed));
                        }}
                      />
                    </div>
                  ))}
                </div>
              ) : null}

              {origin && destination ? (
                <AddStop
                  onAdd={(place) => {
                    if (place.code === origin.code || place.code === destination.code) {
                      toast.warning("Already on the route", `${place.code} is already the origin or destination.`);
                      return;
                    }
                    if (stops.some((s) => s.code === place.code)) {
                      toast.warning("Stop already added", `${place.code} is already a stop.`);
                      return;
                    }
                    setStops([...stops, place]);
                  }}
                />
              ) : null}
            </CardBody>
          </Card>

          {legs.length === 0 ? (
            <EmptyState icon="Route" title="Choose an origin and a destination">
              The legs appear here once both ends are set. Add stops to plan a multi-city journey.
            </EmptyState>
          ) : (
            legs.map((leg, index) => (
              <LegOptions
                key={leg.key}
                index={index}
                from={leg.from}
                to={leg.to}
                date={leg.date}
                onDateChange={(value) =>
                  setLegDates((current) => ({ ...current, [leg.key]: value }))
                }
                selected={selections[leg.key] ?? null}
                onSelect={(option) => choose(leg.key, option)}
                onUseItinerary={(itinerary) => {
                  const hub: JourneyPlace = {
                    code: itinerary.hub_code,
                    name: itinerary.hub_name,
                    city: itinerary.hub_city,
                    country: itinerary.hub_country,
                    timezone: itinerary.hub_tz,
                    kind: "airport",
                    is_city: false,
                    provenance: itinerary.provenance,
                  };
                  if (stops.some((s) => s.code === hub.code)) {
                    toast.warning(
                      "Hub already on the route",
                      `${hub.code} is already a stop on this journey.`,
                    );
                    return;
                  }
                  const before = index === 0 ? origin : stops[index - 1];
                  const after = index + 1 < legs.length ? legs[index + 1].to : destination;
                  const nextStops = [...stops];
                  nextStops.splice(index, 0, hub);
                  setStops(nextStops);
                  dropSelection(legKey(before!, after!));
                  toast.success(
                    `${hub.code} added as a stop`,
                    "Both legs are listed now. Choose a service for each; the connection is already feasible.",
                  );
                }}
              />
            ))
          )}

          <Card>
            <CardHeader
              title="Check the journey"
              subtitle="Optionally test the trip against a disruption before you build it."
              icon="Shield"
            />
            <CardBody className="stack-3">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={checkDisruption}
                  onChange={(event) => setCheckDisruption(event.target.checked)}
                />
                <span>Check against a disruption now</span>
              </label>

              {checkDisruption ? (
                <>
                  <InlineNote icon="Info">
                    The disruption is tagged Simulated and runs through the same detection and recovery
                    pipeline as a live event.
                  </InlineNote>
                  <div className="grid-3">
                    <SelectField
                      label="Disruption"
                      value={disruptionKind}
                      onChange={setDisruptionKind}
                      options={DISRUPTION_KINDS}
                    />
                    <SelectField
                      label="Applies to"
                      value={disruptedLegKey}
                      onChange={setDisruptedLegKey}
                      placeholder="Choose a leg"
                      options={legs
                        .filter((leg) => selections[leg.key])
                        .map((leg) => ({
                          value: leg.key,
                          label: `${leg.from.code} → ${leg.to.code} (${selections[leg.key].service_number ?? "service"})`,
                        }))}
                    />
                    <TextField
                      label="Delay (minutes)"
                      type="number"
                      value={String(delayMinutes)}
                      onChange={(value) => setDelayMinutes(Math.max(0, Number(value) || 0))}
                      hint="Ignored for cancellations and missed connections."
                    />
                  </div>
                </>
              ) : null}
            </CardBody>
          </Card>
        </div>

        <div className="stack-3">
          <Card>
            <CardHeader title="Summary" icon="FileText" />
            <CardBody className="stack-3">
              <Stat label="Legs" value={String(legs.length)} />
              <Stat
                label="Selected"
                value={`${Object.keys(selections).length} of ${legs.length}`}
              />
              <Stat
                label="Fare total"
                value={
                  typeof totalCost === "number"
                    ? `${currency} ${(totalCost / 100).toFixed(2)}`
                    : "—"
                }
                detail="Sum of the selected fares, before any recovery cost."
              />
              <div className="tiny muted">
                Provenance of the selection is shown on each service. Fares for rail are estimates,
                not booking quotes.
              </div>
            </CardBody>
            <div className="card__footer">
              <Button
                variant="primary"
                block
                icon="Check"
                loading={build.isPending}
                disabled={readiness.length > 0}
                onClick={() => build.mutate()}
              >
                Build and check journey
              </Button>
            </div>
          </Card>

          {readiness.length > 0 ? (
            <Card>
              <CardBody className="stack-2">
                <div className="tiny muted">Before you can build</div>
                <ul className="list-plain stack-2">
                  {readiness.map((problem) => (
                    <li key={problem} className="row row-2">
                      <Icon name="Circle" size={10} />
                      <span className="small">{problem}</span>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          ) : null}

          {build.isError ? (
            <Banner tone="disrupted" icon="TriangleAlert">
              {build.error instanceof ApiError
                ? build.error.message
                : "The journey could not be built."}
            </Banner>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- stops */

function AddStop({ onAdd }: { onAdd: (place: JourneyPlace) => void }) {
  const [candidate, setCandidate] = useState<JourneyPlace | null>(null);
  return (
    <div className="row row-2" style={{ alignItems: "flex-end" }}>
      <div style={{ flex: 1 }}>
        <PlacePicker
          label="Add a stop"
          value={candidate}
          onChange={setCandidate}
          placeholder="City or code for an intermediate stop"
        />
      </div>
      <Button
        icon="Plus"
        disabled={!candidate}
        onClick={() => {
          if (candidate) onAdd(candidate);
          setCandidate(null);
        }}
      >
        Add
      </Button>
    </div>
  );
}

/* ---------------------------------------------------------------- legs */

interface LegOptionsProps {
  index: number;
  from: JourneyPlace;
  to: JourneyPlace;
  date: string;
  onDateChange: (value: string) => void;
  selected: JourneyOption | null;
  onSelect: (option: JourneyOption | null) => void;
  onUseItinerary: (itinerary: JourneyItinerary) => void;
}

function LegOptions({
  index,
  from,
  to,
  date,
  onDateChange,
  selected,
  onSelect,
  onUseItinerary,
}: LegOptionsProps) {
  const options = useQuery({
    queryKey: ["journey-options", from.code, to.code, date],
    queryFn: () => api.journeyOptions(from.code, to.code, date),
    enabled: Boolean(date),
    staleTime: 5 * 60 * 1000,
  });

  const payload = options.data;

  return (
    <Card>
      <CardHeader
        title={
          <span className="row row-2">
            <Icon name={
              from.kind === "city" ? "MapPin" :
              from.kind === "rail" ? "TrainFront" :
              from.kind === "bus" ? "Bus" :
              selected?.mode ? modeIcon(selected.mode) : "MapPin"
            } size={16} />
            Leg {index + 1}: {from.city} → {to.city}
          </span>
        }
        subtitle={
          <span className="row row-2 wrap">
            <span>
              {from.city} to {to.city}
            </span>
            {payload ? <Chip variant="info">{payload.distance_km ?? "—"} km</Chip> : null}
            {payload ? <ProvenanceBadge value={payload.provenance} /> : null}
          </span>
        }
        actions={
          <div style={{ width: 180 }}>
            <TextField
              label="Service day"
              type="date"
              value={date}
              onChange={onDateChange}
            />
          </div>
        }
      />
      <CardBody className="stack-3">
        {options.isLoading ? (
          <div className="stack-2">
            <Skeleton height={16} width="60%" />
            <Skeleton height={52} />
            <Skeleton height={52} />
          </div>
        ) : options.isError ? (
          <Banner tone="disrupted" icon="TriangleAlert">
            Services could not be loaded for this leg.
          </Banner>
        ) : !payload || payload.options.length === 0 ? (
          <EmptyState icon="CircleSlash" title="No direct service in the loaded datasets">
            <div className="stack-3">
              <p>
                {payload?.notes[0] ??
                  "No timetable or catalogue answer is available for this pair on this day."}
              </p>
              {payload && payload.itineraries.length > 0 ? (
                <div className="stack-2">
                  <div className="small muted">
                    Connecting itineraries, timed against the minimum connection time
                  </div>
                  {payload.itineraries.map((itinerary) => (
                    <div key={itinerary.key} className="option-row">
                      <Icon name="Route" size={18} />
                      <div className="option-row__main">
                        <div className="row row-2 wrap">
                          <strong>
                            {from.code} → {itinerary.hub_code} → {to.code}
                          </strong>
                          <ProvenanceBadge value={itinerary.provenance} />
                          <Chip variant="done">Connection maintained</Chip>
                        </div>
                        {itinerary.legs.map((leg) => (
                          <div key={leg.key} className="small muted">
                            {leg.service_number} · {leg.origin_code} → {leg.destination_code} ·{" "}
                            departs {leg.departure_local} · arrives {leg.arrival_local}
                          </div>
                        ))}
                        <div className="tiny muted">
                          {itinerary.connection_buffer_minutes} min at {itinerary.hub_name}{" "}
                          (minimum {itinerary.connection_required_minutes} min)
                        </div>
                      </div>
                      <div className="option-row__facts">
                        <div className="small">{itinerary.duration_display}</div>
                        <div className="small">{itinerary.cost_display}</div>
                      </div>
                      <div className="option-row__mark">
                        <Button variant="ghost" onClick={() => onUseItinerary(itinerary)}>
                          Use this connection
                        </Button>
                      </div>
                    </div>
                  ))}
                  <p className="tiny muted">
                    Both legs are modelled from the route data in the loaded datasets. Using one
                    adds the hub as a stop so you can review each leg.
                  </p>
                </div>
              ) : null}
              {payload && payload.connections.length > 0 && payload.itineraries.length === 0 ? (
                <div className="stack-2">
                  <div className="small muted">Connecting routes through a hub</div>
                  <div className="table-wrap">
                    <table className="table table--compact">
                      <thead>
                        <tr>
                          <th scope="col">Route</th>
                          <th scope="col">Connects at</th>
                          <th scope="col">Carriers on file</th>
                        </tr>
                      </thead>
                      <tbody>
                        {payload.connections.map((bridge) => (
                          <tr key={bridge.via}>
                            <td>
                              {from.code} → {bridge.via} → {to.code}
                            </td>
                            <td>
                              {bridge.via_name}
                              <span className="muted small"> · {bridge.via_city}</span>
                            </td>
                            <td className="small muted">
                              {bridge.carriers.length > 0 ? bridge.carriers.join(", ") : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="tiny muted">
                    These are routes both airlines file for the loaded datasets. Add the hub as a
                    stop to see dated services for each leg.
                  </p>
                </div>
              ) : null}
              {payload?.coverage ? <CoverageList coverage={payload.coverage} /> : null}
            </div>
          </EmptyState>
        ) : (
          <>
            <div className="stack-2" role="radiogroup" aria-label={`Services for leg ${index + 1}`}>
              {payload.options.map((option) => {
                const active = selected?.key === option.key;
                return (
                  <button
                    key={option.key}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    className={`option-row${active ? " is-selected" : ""}`}
                    onClick={() => onSelect(active ? null : option)}
                  >
                    <Icon name={modeIcon(option.mode)} size={18} />
                    <div className="option-row__main">
                      <div className="row row-2 wrap">
                        <strong>{option.service_number ?? option.carrier_code}</strong>
                        {option.carrier_name ? (
                          <span className="muted small">{option.carrier_name}</span>
                        ) : null}
                        <ProvenanceBadge value={option.provenance} />
                        {option.refundable ? <Chip variant="done">Refundable</Chip> : null}
                      </div>
                      <div className="small muted">
                        Departs {option.departure_local} · arrives {option.arrival_local}
                      </div>
                      {option.note ? <div className="tiny muted">{option.note}</div> : null}
                    </div>
                    <div className="option-row__facts">
                      <div className="small">{formatDuration(option.duration_minutes)}</div>
                      <div className="small">{option.cost_display}</div>
                    </div>
                    <div className="option-row__mark">
                      {active ? <Icon name="CircleCheck" size={18} /> : <Icon name="Circle" size={18} />}
                    </div>
                  </button>
                );
              })}
            </div>
            {payload.sources.length > 0 ? (
              <InlineNote icon="Database">
                Sources: {payload.sources.join(" · ")}
                {payload.notes.length > 0 ? ` — ${payload.notes.join(" ")}` : ""}
              </InlineNote>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours === 0) return `${mins}m`;
  return `${hours}h ${mins.toString().padStart(2, "0")}m`;
}

function CoverageList({ coverage }: { coverage: JourneyCoverage }) {
  const groups: { title: string; source: string; rows: string[] }[] = [];

  if (coverage.rail_pairs.length > 0) {
    const window =
      coverage.rail_valid_from && coverage.rail_valid_to
        ? ` · valid ${coverage.rail_valid_from} to ${coverage.rail_valid_to}`
        : "";
    groups.push({
      title: "Rail from the published timetable",
      source: `${coverage.rail_source ?? "DELFI e.V. / GTFS.de"}${window}`,
      rows: coverage.rail_pairs.map((pair) => pair.detail ?? pair.label),
    });
  }
  return (
    <div className="stack-3">
      <div className="small muted">Loaded coverage</div>
      {groups.map((group) => (
        <div key={group.title} className="stack-2">
          <div className="row row-2 wrap">
            <span className="small">{group.title}</span>
            <ProvenanceBadge value="REFERENCE" />
          </div>
          <ul className="list-plain stack-2">
            {group.rows.map((row) => (
              <li key={row} className="row row-2">
                <Icon name="MapPin" size={12} />
                <span className="small">{row}</span>
              </li>
            ))}
          </ul>
          <div className="tiny muted">Source: {group.source}</div>
        </div>
      ))}
      {groups.length === 0 ? (
        <div className="small muted">No datasets are loaded in this build.</div>
      ) : null}
    </div>
  );
}
