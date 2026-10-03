import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader, Divider, Banner } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { TextField, CheckboxField, SelectField } from "../components/ui/Form";
import { Icon } from "../components/ui/Icon";
import { SkeletonPage } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import { initials, money } from "../lib/format";

const SEAT_OPTIONS = [
  { value: "aisle", label: "Aisle" },
  { value: "window", label: "Window" },
  { value: "no_preference", label: "No preference" },
];

const CABIN_OPTIONS = [
  { value: "economy", label: "Economy" },
  { value: "premium_economy", label: "Premium economy" },
  { value: "business", label: "Business" },
  { value: "first", label: "First" },
];

export function ProfilePage() {
  const { user, setUser } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [form, setForm] = useState({
    full_name: "",
    phone: "",
    home_airport: "",
    preferred_airlines: "",
    preferred_seat: "aisle",
    preferred_cabin: "business",
    budget_minor: "900",
    accessibility_needs: "",
    quiet_room: true,
    late_checkout: true,
    prefer_rail: true,
    car_class: "executive",
  });

  useEffect(() => {
    if (!user) return;
    setForm({
      full_name: user.full_name,
      phone: user.phone ?? "",
      home_airport: user.home_airport ?? "",
      preferred_airlines: (user.preferred_airlines ?? []).join(", "),
      preferred_seat: user.preferred_seat ?? "aisle",
      preferred_cabin: user.preferred_cabin ?? "business",
      budget_minor: user.budget_minor ? String(user.budget_minor / 100) : "",
      accessibility_needs: user.accessibility_needs ?? "",
      quiet_room: Boolean(user.hotel_preferences?.quiet_room),
      late_checkout: Boolean(user.hotel_preferences?.late_checkout),
      prefer_rail: Boolean(user.ground_preferences?.prefer_rail),
      car_class: String(user.ground_preferences?.car_class ?? "executive"),
    });
  }, [user]);

  const save = useMutation({
    mutationFn: () =>
      api.updateProfile({
        full_name: form.full_name.trim(),
        phone: form.phone.trim() || null,
        home_airport: form.home_airport.trim().toUpperCase() || null,
        preferred_airlines: form.preferred_airlines
          .split(",")
          .map((code) => code.trim().toUpperCase())
          .filter(Boolean),
        preferred_seat: form.preferred_seat,
        preferred_cabin: form.preferred_cabin,
        budget_minor: form.budget_minor ? Math.round(Number(form.budget_minor) * 100) : null,
        accessibility_needs: form.accessibility_needs.trim() || null,
        hotel_preferences: {
          quiet_room: form.quiet_room,
          late_checkout: form.late_checkout,
        },
        ground_preferences: {
          prefer_rail: form.prefer_rail,
          car_class: form.car_class,
        },
      }),
    onSuccess: (data) => {
      setUser(data.user);
      void queryClient.invalidateQueries();
      toast.success("Profile saved", "Your preferences are used when plans are built and scored.");
    },
    onError: (error: Error) => toast.error("Could not save your profile", error.message),
  });

  if (!user) return <SkeletonPage />;

  return (
    <>
      <PageHeader
        title="Profile"
        subtitle="Passenger details and travel preferences used across recovery plans"
        actions={
          <>
            <Button
              variant="primary"
              icon="Save"
              loading={save.isPending}
              onClick={() => save.mutate()}
            >
              Save changes
            </Button>
          </>
        }
      />

      <div className="stack stack-5">
        <Card>
          <CardBody>
            <div className="row row-4 wrap">
              <span className="avatar-lg">{initials(user.full_name)}</span>
              <div className="grow">
                <div className="h3">{user.full_name}</div>
                <div className="secondary small">{user.email}</div>
                <div className="row row-2 wrap" style={{ marginTop: "var(--s-2)" }}>
                  <span className="tag">
                    <Icon name="User" size={11} />
                    {user.role === "travel_manager"
                      ? "Travel Manager"
                      : user.role === "admin"
                        ? "Administrator"
                        : "Traveller"}
                  </span>
                  {user.home_airport ? (
                    <span className="tag">
                      <Icon name="Plane" size={11} />
                      Home airport {user.home_airport}
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
          </CardBody>
        </Card>

        <div className="grid grid-2">
          <Card>
            <CardHeader title="Passenger details" icon="User" />
            <CardBody className="stack stack-4">
              <TextField
                label="Full name"
                value={form.full_name}
                onChange={(value) => setForm((current) => ({ ...current, full_name: value }))}
                required
              />
              <TextField label="Email" value={user.email} onChange={() => undefined} disabled hint="Email is the sign-in identity." />
              <TextField
                label="Phone"
                value={form.phone}
                onChange={(value) => setForm((current) => ({ ...current, phone: value }))}
                type="tel"
                placeholder="+91 44 4000 1200"
              />
              <TextField
                label="Home airport"
                value={form.home_airport}
                onChange={(value) => setForm((current) => ({ ...current, home_airport: value }))}
                placeholder="MAA"
                hint="IATA code of your usual departure airport."
              />
              <TextField
                label="Accessibility needs"
                value={form.accessibility_needs}
                onChange={(value) => setForm((current) => ({ ...current, accessibility_needs: value }))}
                placeholder="Optional"
                hint="Used as a constraint when plans are checked."
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Travel preferences" subtitle="Applied when plans are scored" icon="SlidersHorizontal" />
            <CardBody className="stack stack-4">
              <TextField
                label="Preferred airlines"
                value={form.preferred_airlines}
                onChange={(value) => setForm((current) => ({ ...current, preferred_airlines: value }))}
                placeholder="LH, AI"
                hint="Comma-separated IATA airline codes."
              />
              <SelectField
                label="Preferred seat"
                value={form.preferred_seat}
                onChange={(value) => setForm((current) => ({ ...current, preferred_seat: value }))}
                options={SEAT_OPTIONS}
              />
              <SelectField
                label="Preferred cabin"
                value={form.preferred_cabin}
                onChange={(value) => setForm((current) => ({ ...current, preferred_cabin: value }))}
                options={CABIN_OPTIONS}
              />
              <TextField
                label={`Budget per disruption (${user.budget_currency})`}
                value={form.budget_minor}
                onChange={(value) => setForm((current) => ({ ...current, budget_minor: value }))}
                type="number"
                inputMode="decimal"
                hint={
                  form.budget_minor
                    ? `Plans above ${money(Math.round(Number(form.budget_minor) * 100), user.budget_currency)} score lower on cost.`
                    : "Leave blank for no budget preference."
                }
              />
              <Divider />
              <div className="stack stack-3">
                <span className="eyebrow">Hotel preferences</span>
                <CheckboxField
                  label="Quiet room"
                  checked={form.quiet_room}
                  onChange={(checked) => setForm((current) => ({ ...current, quiet_room: checked }))}
                />
                <CheckboxField
                  label="Late check-out"
                  checked={form.late_checkout}
                  onChange={(checked) => setForm((current) => ({ ...current, late_checkout: checked }))}
                />
              </div>
              <Divider />
              <div className="stack stack-3">
                <span className="eyebrow">Ground preferences</span>
                <CheckboxField
                  label="Prefer rail over short flights"
                  checked={form.prefer_rail}
                  onChange={(checked) => setForm((current) => ({ ...current, prefer_rail: checked }))}
                  hint="Rail is still checked as a separate mode, never combined with a flight on one leg."
                />
                <SelectField
                  label="Car class"
                  value={form.car_class}
                  onChange={(value) => setForm((current) => ({ ...current, car_class: value }))}
                  options={[
                    { value: "standard", label: "Standard" },
                    { value: "executive", label: "Executive" },
                    { value: "premium", label: "Premium" },
                  ]}
                />
              </div>
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader title="Travel documents" subtitle="Stored masked and never displayed in full" icon="Lock" />
          <CardBody>
            <div className="grid grid-3">
              <div>
                <div className="eyebrow">Passport number</div>
                <div className="mono" style={{ marginTop: "var(--s-1)" }}>
                  {user.passport_masked ?? "Not on file"}
                </div>
                <p className="tiny muted" style={{ marginTop: "var(--s-1)" }}>
                  Masked at rest. Never logged and never shown in full.
                </p>
              </div>
              <div>
                <div className="eyebrow">Nationality</div>
                <div style={{ marginTop: "var(--s-1)" }}>{user.passport_nationality ?? "Not on file"}</div>
              </div>
              <div>
                <div className="eyebrow">Expiry</div>
                <div style={{ marginTop: "var(--s-1)" }}>{user.passport_expiry ?? "Not on file"}</div>
              </div>
            </div>

            <div style={{ marginTop: "var(--s-4)" }}>
              <Banner tone="info" icon="Info" title="Visa and transit">
                Visa and transit rules come from a curated rule table with a source and a last-verified
                date. Always verify with the embassy or airline before travel.
              </Banner>
            </div>
          </CardBody>
        </Card>

        <div className="row row-2 wrap" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" icon="Save" loading={save.isPending} onClick={() => save.mutate()}>
            Save changes
          </Button>
        </div>
      </div>
    </>
  );
}
