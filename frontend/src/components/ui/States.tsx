import type { ReactNode } from "react";
import { Icon } from "./Icon";

/* --------------------------------------------------------------- states */

export function Skeleton({ height = 12, width, className = "" }: { height?: number; width?: string; className?: string }) {
  return <div className={`skeleton ${className}`} style={{ height, width }} aria-hidden="true" />;
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card card--flat">
      <div className="card__body">
        <div className="skeleton skeleton--title" />
        {Array.from({ length: lines }).map((_, index) => (
          <div
            key={index}
            className="skeleton skeleton--text"
            style={{ width: `${100 - index * 12}%` }}
          />
        ))}
      </div>
    </div>
  );
}

export function SkeletonPage() {
  return (
    <div className="stack stack-5" aria-busy="true" aria-live="polite">
      <div>
        <div className="skeleton skeleton--title" style={{ width: "30%", height: 24 }} />
        <div className="skeleton skeleton--text" style={{ width: "50%" }} />
      </div>
      <div className="grid grid-cards">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={4} />
        <SkeletonCard lines={4} />
      </div>
      <SkeletonCard lines={6} />
      <span className="visually-hidden">Loading</span>
    </div>
  );
}

export function SkeletonTable({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="card card--flat" aria-busy="true">
      <div className="card__body">
        <div className="skeleton skeleton--title" />
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div key={rowIndex} className="row row-4" style={{ marginBottom: "var(--s-3)" }}>
            {Array.from({ length: columns }).map((_, columnIndex) => (
              <div
                key={columnIndex}
                className="skeleton skeleton--text"
                style={{ flex: 1, height: 14 }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- empty state */

interface EmptyStateProps {
  icon?: string;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}

export function EmptyState({ icon = "CircleSlash", title, children, actions }: EmptyStateProps) {
  return (
    <div className="empty">
      <span className="empty__icon">
        <Icon name={icon} size={28} strokeWidth={1.5} />
      </span>
      <div className="empty__title">{title}</div>
      {children ? <div className="empty__body">{children}</div> : null}
      {actions ? <div className="empty__actions">{actions}</div> : null}
    </div>
  );
}

/* ---------------------------------------------------------- error state */

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  retryLabel = "Try again",
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div className="empty" role="alert">
      <span className="empty__icon" style={{ color: "var(--status-disrupted)" }}>
        <Icon name="TriangleAlert" size={28} strokeWidth={1.5} />
      </span>
      <div className="empty__title">{title}</div>
      <div className="empty__body">{message}</div>
      {onRetry ? (
        <div className="empty__actions">
          <button type="button" className="btn" onClick={onRetry}>
            <Icon name="RefreshCw" size={15} />
            {retryLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------- spinner */

export function InlineSpinner({ label }: { label?: string }) {
  return (
    <span className="row row-2 muted small">
      <Icon name="LoaderCircle" size={15} className="spin" />
      {label ?? "Loading"}
    </span>
  );
}

/* ------------------------------------------------------------ inline note */

export function InlineNote({ icon = "Info", children }: { icon?: string; children: ReactNode }) {
  return (
    <p className="inline-note">
      <Icon name={icon} size={13} />
      <span>{children}</span>
    </p>
  );
}

/* -------------------------------------------------------------- progress */

export function ProgressBar({
  value,
  tone,
  label,
}: {
  value: number;
  tone?: "accent" | "risk" | "disrupted";
  label?: string;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      className="progress"
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div
        className={`progress__bar ${tone && tone !== "accent" ? `progress__bar--${tone}` : ""}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/* ----------------------------------------------------------- score meter */

export function ScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="score-bar">
      <div className="score-bar__track">
        <div className="score-bar__fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="score-bar__value">{value.toFixed(0)}</span>
    </div>
  );
}
