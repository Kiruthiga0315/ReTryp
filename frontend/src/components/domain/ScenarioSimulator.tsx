import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../hooks/useAuth";
import { useCurrentTrip } from "../../hooks/useTrip";
import { Button } from "../ui/Button";
import { SlideOver, ConfirmDialog } from "../ui/Dialog";
import { SelectField, TextField } from "../ui/Form";
import { Banner } from "../ui/Card";
import { InlineNote } from "../ui/States";
import { Icon } from "../ui/Icon";
import { useToast } from "../ui/Toast";
import { ProvenanceBadge } from "../ui/Badge";

const DELAY_KINDS = new Set(["flight_delay"]);

/** Admin-only Scenario Simulator.
 *
 *  Everything injected here is tagged SIMULATED and enters the same
 *  detection pipeline a live feed would use. It exists so an operator can
 *  exercise the recovery pipeline deterministically. */
export function ScenarioSimulator() {
  const { user } = useAuth();
  const trip = useCurrentTrip();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("flight_delay");
  const [target, setTarget] = useState("");
  const [delayMinutes, setDelayMinutes] = useState("225");
  const [detail, setDetail] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);

  const scenarios = useQuery({
    queryKey: ["scenarios"],
    queryFn: api.scenarios,
    enabled: open && user?.role === "admin",
    staleTime: 10 * 60 * 1000,
  });

  const inject = useMutation({
    mutationFn: api.inject,
    onSuccess: (data) => {
      void queryClient.invalidateQueries();
      toast.success(
        `Disruption injected: ${data.disruption.title}`,
        `${data.plans.length} recovery ${data.plans.length === 1 ? "plan" : "plans"} prepared in cycle ${data.cycle}.`,
      );
      setDetail("");
    },
    onError: (error: Error) => toast.error("Could not inject the disruption", error.message),
  });

  const reset = useMutation({
    mutationFn: () => api.resetRecovery(trip.data!.trip.id),
    onSuccess: (data) => {
      void queryClient.invalidateQueries();
      const { disruptions, plans } = data.removed;
      toast.success(
        "Recovery state reset",
        `Removed ${disruptions} disruption${disruptions === 1 ? "" : "s"} and ${plans} plan${plans === 1 ? "" : "s"}. The booked itinerary is restored.`,
      );
    },
    onError: (error: Error) => toast.error("Could not reset the trip", error.message),
  });

  if (user?.role !== "admin") return null;

  const segments = trip.data?.segments ?? [];
  const hotels = trip.data?.hotels ?? [];
  const ground = trip.data?.ground ?? [];

  const targetOptions = [
    ...segments.map((segment) => ({
      value: `segment:${segment.id}`,
      label: `${segment.service_number ?? segment.mode_label} · ${segment.origin.code} → ${segment.destination.code} (${segment.status_label})`,
    })),
    ...hotels.map((hotel) => ({ value: `hotel:${hotel.id}`, label: `Hotel · ${hotel.name}` })),
    ...ground.map((item) => ({ value: `ground:${item.id}`, label: `Ground · ${item.from_label}` })),
  ];

  function submit() {
    if (!trip.data) return;
    const [targetKind, targetId] = target ? target.split(":") : [null, null];
    inject.mutate({
      trip_id: trip.data.trip.id,
      kind,
      segment_id: targetKind === "segment" ? targetId : null,
      hotel_id: targetKind === "hotel" ? targetId : null,
      ground_id: targetKind === "ground" ? targetId : null,
      delay_minutes: DELAY_KINDS.has(kind) ? Number(delayMinutes) || null : null,
      detail: detail.trim() || null,
    });
  }

  return (
    <>
      <button
        type="button"
        className="btn btn--sm"
        onClick={() => setOpen(true)}
        style={{
          position: "fixed",
          bottom: "var(--s-4)",
          left: "var(--s-4)",
          zIndex: 45,
          boxShadow: "var(--shadow-md)",
          background: "var(--ink-800)",
          borderColor: "var(--ink-800)",
          color: "var(--white)",
        }}
        aria-label="Open scenario simulator"
      >
        <Icon name="SlidersHorizontal" size={14} />
        Scenario simulator
      </button>

      <SlideOver open={open} onClose={() => setOpen(false)} title="Scenario simulator">
        <div className="stack stack-4">
          <Banner tone="info" icon="Info" title="Scenario Simulator">
            Inject a disruption into the current journey. Everything created here is tagged
            SIMULATED and runs through the same detection, impact and recovery pipeline a live
            feed would use.
          </Banner>

          <div className="row row-2 wrap">
            <ProvenanceBadge value="SIMULATED" />
            <span className="tiny muted">
              Admin only. A live feed cannot be asked to produce this scenario on demand, so it is injected here.
            </span>
          </div>

          <SelectField
            label="Disruption type"
            value={kind}
            onChange={setKind}
            options={(scenarios.data?.kinds ?? []).map((item) => ({
              value: item.value,
              label: item.label,
            }))}
            hint="Each type follows the same pipeline; the constraint checks differ."
          />

          <SelectField
            label="Affected booking"
            value={target}
            onChange={setTarget}
            placeholder="Choose a segment, hotel or transfer"
            options={targetOptions}
            hint="Leave blank to target the first segment that can still be disrupted."
          />

          {DELAY_KINDS.has(kind) ? (
            <TextField
              label="Delay (minutes)"
              value={delayMinutes}
              onChange={setDelayMinutes}
              type="number"
              inputMode="numeric"
              hint="Example: 225 minutes is 3h 45m."
            />
          ) : null}

          <TextField
            label="Detail (optional)"
            value={detail}
            onChange={setDetail}
            placeholder="Short reason shown on the disruption card"
          />

          <Button
            variant="primary"
            icon="Send"
            onClick={submit}
            loading={inject.isPending}
            disabled={!trip.data}
            block
          >
            Inject disruption
          </Button>

          <InlineNote icon="ShieldCheck">
            The current journey is {trip.data?.trip.reference ?? "unavailable"}. Cycle{" "}
            {Math.max(1, (trip.data?.trip.disruption_count ?? 0))} has already been recorded.
          </InlineNote>

          <div className="stack stack-2" style={{ borderTop: "1px solid var(--line)", paddingTop: "var(--s-4)" }}>
            <Button
              variant="ghost"
              icon="RotateCcw"
              onClick={() => setConfirmReset(true)}
              disabled={!trip.data || reset.isPending}
              loading={reset.isPending}
              block
            >
              Reset to booked itinerary
            </Button>
            <span className="tiny muted">
              Clears the trip's disruptions, plans and recovered legs and restores the original
              booking, so the pipeline can be exercised again from the start.
            </span>
          </div>
        </div>
      </SlideOver>

      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        onConfirm={() => {
          reset.mutate();
          setConfirmReset(false);
        }}
        title="Reset this trip's recovery state?"
        confirmLabel="Reset trip"
        confirmVariant="danger"
        busy={reset.isPending}
      >
        <p>
          This removes every disruption, recovery plan, notification and recovered leg for{" "}
          {trip.data?.trip.reference ?? "this trip"}, and restores the segments, hotel and transfer
          to exactly as booked. The original bookings are kept.
        </p>
      </ConfirmDialog>
    </>
  );
}
