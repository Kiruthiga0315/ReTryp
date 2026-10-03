import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader, Banner } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { CheckboxField, SelectField } from "../components/ui/Form";
import { Icon } from "../components/ui/Icon";
import { ProvenanceBadge, StatusChip } from "../components/ui/Badge";
import { SkeletonPage } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import { displayCurrencyFor } from "../lib/format";

const CURRENCIES = [
  { value: "INR", label: "Indian Rupee (INR)" },
  { value: "EUR", label: "Euro (EUR)" },
  { value: "USD", label: "US Dollar (USD)" },
  { value: "GBP", label: "Pound Sterling (GBP)" },
  { value: "CHF", label: "Swiss Franc (CHF)" },
];

const TIMEZONES = [
  { value: "Europe/Berlin", label: "Europe/Berlin (CET/CEST)" },
  { value: "Asia/Kolkata", label: "Asia/Kolkata (IST)" },
  { value: "Europe/London", label: "Europe/London (GMT/BST)" },
  { value: "America/New_York", label: "America/New_York (ET)" },
  { value: "UTC", label: "UTC" },
];

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "de", label: "Deutsch" },
  { value: "hi", label: "हिन्दी" },
];

export function SettingsPage() {
  const { user, setUser } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [settings, setSettings] = useState({
    disruption: true,
    plan_ready: true,
    execution: true,
    monitoring: true,
    currency: displayCurrencyFor(user),
    language: "en",
    timezone: "Europe/Berlin",
    avoid_overnight_connections: false,
    share_itinerary_with_manager: true,
  });

  useEffect(() => {
    if (!user) return;
    setSettings({
      disruption: Boolean(user.settings?.notifications?.disruption),
      plan_ready: Boolean(user.settings?.notifications?.plan_ready),
      execution: Boolean(user.settings?.notifications?.execution),
      monitoring: Boolean(user.settings?.notifications?.monitoring),
      currency: displayCurrencyFor(user),
      language: user.settings?.language ?? "en",
      timezone: user.settings?.timezone ?? "Europe/Berlin",
      avoid_overnight_connections: Boolean(
        user.settings?.travel_preferences?.avoid_overnight_connections,
      ),
      share_itinerary_with_manager: Boolean(user.settings?.privacy?.share_itinerary_with_manager),
    });
  }, [user]);

  const save = useMutation({
    mutationFn: () =>
      api.updateSettings({
        notifications: {
          disruption: settings.disruption,
          plan_ready: settings.plan_ready,
          execution: settings.execution,
          monitoring: settings.monitoring,
        },
        currency: settings.currency,
        language: settings.language,
        timezone: settings.timezone,
        travel_preferences: {
          avoid_overnight_connections: settings.avoid_overnight_connections,
        },
        privacy: { share_itinerary_with_manager: settings.share_itinerary_with_manager },
      }),
    onSuccess: (data) => {
      setUser(data.user);
      void queryClient.invalidateQueries();
      toast.success("Settings saved", "Your preferences now apply across the app.");
    },
    onError: (error: Error) => toast.error("Could not save settings", error.message),
  });

  const providers = useQuery({
    queryKey: ["provider-health"],
    queryFn: api.providerHealth,
    staleTime: 5 * 60 * 1000,
  });

  const dataStatus = useQuery({
    queryKey: ["data-status"],
    queryFn: api.dataStatus,
    staleTime: 5 * 60 * 1000,
  });

  if (!user) return <SkeletonPage />;

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Notifications, regional formats, travel preferences and privacy"
        actions={
          <Button variant="primary" icon="Save" loading={save.isPending} onClick={() => save.mutate()}>
            Save settings
          </Button>
        }
      />

      <div className="stack stack-5">
        <div className="grid grid-2">
          <Card>
            <CardHeader title="Notifications" subtitle="Which events raise a notification" icon="Bell" />
            <CardBody className="stack stack-3">
              <CheckboxField
                label="Disruption detected"
                checked={settings.disruption}
                onChange={(checked) => setSettings((current) => ({ ...current, disruption: checked }))}
                hint="A segment breaks or a connection becomes infeasible."
              />
              <CheckboxField
                label="Recovery plan ready"
                checked={settings.plan_ready}
                onChange={(checked) => setSettings((current) => ({ ...current, plan_ready: checked }))}
                hint="One or more complete plans have been built."
              />
              <CheckboxField
                label="Execution updates"
                checked={settings.execution}
                onChange={(checked) => setSettings((current) => ({ ...current, execution: checked }))}
                hint="Changes requested, pending provider confirmation, or recorded offline."
              />
              <CheckboxField
                label="Monitoring findings"
                checked={settings.monitoring}
                onChange={(checked) => setSettings((current) => ({ ...current, monitoring: checked }))}
                hint="A monitoring check finds the active plan is no longer valid."
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Region and formats" icon="Globe" />
            <CardBody className="stack stack-4">
              <SelectField
                label="Currency"
                value={settings.currency}
                onChange={(value) => setSettings((current) => ({ ...current, currency: value }))}
                options={CURRENCIES}
                hint="Used for cost displays and budget scoring."
              />
              <SelectField
                label="Language"
                value={settings.language}
                onChange={(value) => setSettings((current) => ({ ...current, language: value }))}
                options={LANGUAGES}
              />
              <SelectField
                label="Time zone"
                value={settings.timezone}
                onChange={(value) => setSettings((current) => ({ ...current, timezone: value }))}
                options={TIMEZONES}
                hint="Segment times are always shown in each airport's local zone. This sets your reference zone."
              />
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader title="Travel preferences" subtitle="Used as constraints when plans are checked" icon="SlidersHorizontal" />
          <CardBody className="stack stack-3">
            <CheckboxField
              label="Avoid overnight connections"
              checked={settings.avoid_overnight_connections}
              onChange={(checked) =>
                setSettings((current) => ({ ...current, avoid_overnight_connections: checked }))
              }
              hint="Plans that wait overnight at a connection score lower."
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Privacy" icon="Lock" />
          <CardBody className="stack stack-3">
            <CheckboxField
              label="Share itinerary with my Travel Manager"
              checked={settings.share_itinerary_with_manager}
              onChange={(checked) =>
                setSettings((current) => ({ ...current, share_itinerary_with_manager: checked }))
              }
              hint="Managers can only see trips belonging to travellers on their account."
            />
            <Banner tone="info" icon="Info" title="Passport data">
              Passport details are stored masked and are never logged or shown in full. Visa and
              transit rules always carry a source and a last-verified date.
            </Banner>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Data sources"
            subtitle="Where each data point comes from, and its published validity window"
            icon="Database"
          />
          <CardBody flush>
            {dataStatus.isLoading ? (
              <p className="small muted" style={{ padding: "var(--s-5)" }}>
                Reading data sources…
              </p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Dataset</th>
                      <th>Status</th>
                      <th>Provenance</th>
                      <th>Validity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(dataStatus.data?.sources ?? []).map((source) => (
                      <tr key={source.name}>
                        <td className="cell-primary">{source.name}</td>
                        <td className="small secondary">{source.detail}</td>
                        <td>
                          {source.loaded ? (
                            <StatusChip kind="action" value="confirmed" size="sm" />
                          ) : (
                            <span className="small muted">Not loaded</span>
                          )}
                        </td>
                        <td>
                          <ProvenanceBadge value={source.provenance} />
                        </td>
                        <td className="small secondary">
                          {source.valid_from && source.valid_to
                            ? `${source.valid_from} to ${source.valid_to}`
                            : "Static reference"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
          <div className="card__footer">
            <span className="tiny muted" style={{ maxWidth: "62ch" }}>
              {dataStatus.data?.note ?? "Data status is being read."}
            </span>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Data providers"
            subtitle="Every integration is optional. An unconfigured provider reports itself unavailable."
            icon="Server"
          />
          <CardBody flush>
            {providers.isLoading ? (
              <p className="small muted" style={{ padding: "var(--s-5)" }}>
                Checking providers…
              </p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Provider</th>
                      <th>Integration</th>
                      <th>Configured</th>
                      <th>Circuit</th>
                      <th>Last error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(providers.data?.providers ?? []).map((provider) => (
                      <tr key={provider.name}>
                        <td className="cell-primary">{provider.name}</td>
                        <td className="mono small secondary">{provider.provider}</td>
                        <td>
                          {provider.configured ? (
                            <StatusChip kind="action" value="confirmed" size="sm" />
                          ) : (
                            <span className="small muted">Not configured</span>
                          )}
                        </td>
                        <td>
                          <span className="tag">{provider.circuit}</span>
                        </td>
                        <td className="small secondary">
                          {provider.last_error ?? "No errors recorded"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
          <div className="card__footer">
            <div className="row row-2 wrap">
              <ProvenanceBadge value={providers.data?.data_status === "live" ? "LIVE" : "UNAVAILABLE"} />
              <span className="tiny muted">
                {providers.data?.note ?? "Provider health is calculated from the configured keys."}
              </span>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Account" icon="User" />
          <CardBody>
            <div className="grid grid-2">
              <div>
                <div className="eyebrow">Signed in as</div>
                <div style={{ marginTop: "var(--s-1)" }}>{user.email}</div>
                <div className="row row-2" style={{ marginTop: "var(--s-2)" }}>
                  <span className="tag">
                    <Icon name="User" size={11} />
                    {user.role === "travel_manager"
                      ? "Travel Manager"
                      : user.role === "admin"
                        ? "Administrator"
                        : "Traveller"}
                  </span>
                </div>
              </div>
              <div>
                <div className="eyebrow">Session</div>
                <div style={{ marginTop: "var(--s-1)" }} className="small secondary">
                  Sessions are cookie-based and expire automatically. Role-based access applies to
                  every endpoint.
                </div>
              </div>
            </div>
          </CardBody>
        </Card>

        <div className="row row-2 wrap" style={{ justifyContent: "flex-end" }}>
          <Button variant="primary" icon="Save" loading={save.isPending} onClick={() => save.mutate()}>
            Save settings
          </Button>
        </div>
      </div>
    </>
  );
}
