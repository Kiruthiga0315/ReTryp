import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { PageHeader } from "../components/layout/AppShell";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { Button, Segmented } from "../components/ui/Button";
import { SelectField } from "../components/ui/Form";
import { Icon } from "../components/ui/Icon";
import { ProvenanceBadge, StatusChip } from "../components/ui/Badge";
import { EmptyState, ErrorState, SkeletonTable } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import { relativeTime } from "../lib/format";
import type { Notification } from "../api/types";

const KIND_ICON: Record<string, string> = {
  disruption: "TriangleAlert",
  plan_ready: "FileText",
  execution: "Send",
  monitoring: "Activity",
  compensation: "CircleDollarSign",
  system: "Info",
};

const SEVERITY_TONE: Record<string, string> = {
  critical: "disrupted",
  high: "disrupted",
  medium: "risk",
  low: "info",
};

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [kindFilter, setKindFilter] = useState("");

  const notifications = useQuery({
    queryKey: ["notifications", kindFilter],
    queryFn: () => api.notifications(kindFilter ? { kind: kindFilter } : undefined),
  });

  const markRead = useMutation({
    mutationFn: (payload: { ids?: string[]; all?: boolean }) => api.markNotificationsRead(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
      toast.success("Notifications updated");
    },
    onError: (error: Error) => toast.error("Could not update notifications", error.message),
  });

  const items = useMemo(() => {
    const list = notifications.data?.notifications ?? [];
    return filter === "unread" ? list.filter((item) => !item.read) : list;
  }, [notifications.data, filter]);

  if (notifications.isLoading) return <SkeletonTable rows={6} columns={2} />;
  if (notifications.isError) {
    return (
      <ErrorState
        title="Cannot load notifications"
        message={(notifications.error as Error)?.message ?? "Notifications could not be loaded."}
        onRetry={() => void notifications.refetch()}
      />
    );
  }

  const unread = notifications.data?.unread_count ?? 0;

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle={
          unread > 0
            ? `${unread} unread of ${notifications.data?.count ?? 0}`
            : `All ${notifications.data?.count ?? 0} read`
        }
        actions={
          <>
            <Button
              size="sm"
              icon="CheckCheck"
              onClick={() => markRead.mutate({ all: true })}
              disabled={unread === 0}
              loading={markRead.isPending}
            >
              Mark all read
            </Button>
            <ProvenanceBadge value="LIVE" />
          </>
        }
      />

      <Card>
        <CardHeader
          title="All notifications"
          subtitle="Wording written for people, not machines"
          icon="Bell"
          actions={
            <div className="row row-2 wrap">
              <Segmented
                ariaLabel="Read state"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: "all", label: "All" },
                  { value: "unread", label: `Unread${unread ? ` (${unread})` : ""}` },
                ]}
              />
              <div style={{ minWidth: 180 }}>
                <SelectField
                  label=""
                  value={kindFilter}
                  onChange={setKindFilter}
                  placeholder="All types"
                  options={[
                    { value: "disruption", label: "Disruption" },
                    { value: "plan_ready", label: "Plan ready" },
                    { value: "execution", label: "Execution" },
                    { value: "monitoring", label: "Monitoring" },
                  ]}
                />
              </div>
            </div>
          }
        />
        <CardBody flush>
          {items.length === 0 ? (
            <EmptyState icon="Bell" title="Nothing here">
              {filter === "unread"
                ? "Every notification has been read."
                : "Notifications about disruptions, plans and execution will appear here."}
            </EmptyState>
          ) : (
            <div>
              {items.map((notification) => (
                <NotificationRow
                  key={notification.id}
                  notification={notification}
                  onMarkRead={() => markRead.mutate({ ids: [notification.id] })}
                />
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </>
  );
}

function NotificationRow({
  notification,
  onMarkRead,
}: {
  notification: Notification;
  onMarkRead: () => void;
}) {
  const tone = SEVERITY_TONE[notification.severity] ?? "info";
  return (
    <div className="notification-row" data-unread={!notification.read}>
      {!notification.read ? <span className="notification-row__unread" aria-label="Unread" /> : <span style={{ width: 7 }} />}
      <span
        className="notification-row__icon"
        style={{
          background:
            tone === "disrupted"
              ? "var(--status-disrupted-bg)"
              : tone === "risk"
                ? "var(--status-risk-bg)"
                : "var(--status-info-bg)",
          color:
            tone === "disrupted"
              ? "var(--status-disrupted)"
              : tone === "risk"
                ? "var(--status-risk)"
                : "var(--status-info)",
        }}
      >
        <Icon name={KIND_ICON[notification.kind] ?? "Bell"} size={15} />
      </span>

      <div className="grow">
        <div className="row row-2 wrap">
          <span style={{ fontWeight: 600 }}>{notification.title}</span>
          <StatusChip kind="severity" value={notification.severity} size="sm" />
          <ProvenanceBadge value={notification.provenance} />
        </div>
        <p className="small secondary" style={{ marginTop: "var(--s-1)" }}>
          {notification.body}
        </p>
        <div className="row row-2 wrap" style={{ marginTop: "var(--s-2)" }}>
          <span className="tiny muted">{relativeTime(notification.created_at_utc)}</span>
          <span aria-hidden="true" className="tiny muted">
            ·
          </span>
          <span className="tiny muted">
            {new Date(notification.created_at_utc).toLocaleString("en-GB")}
          </span>
          <span className="tag">{notification.kind.replace(/_/g, " ")}</span>
        </div>
      </div>

      <div className="row row-2" style={{ flex: "none" }}>
        {notification.trip_id ? (
          <Link to="/recovery" className="btn btn--sm btn--ghost">
            <Icon name="Route" size={13} />
            Recovery
          </Link>
        ) : null}
        {!notification.read ? (
          <Button size="sm" variant="ghost" icon="Check" onClick={onMarkRead}>
            Mark read
          </Button>
        ) : null}
      </div>
    </div>
  );
}
