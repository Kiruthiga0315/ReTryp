import type { ReactNode } from "react";
import { Icon } from "./Icon";

interface CardProps {
  children: ReactNode;
  className?: string;
  flat?: boolean;
  interactive?: boolean;
  selected?: boolean;
  as?: "div" | "section" | "article" | "li";
}

export function Card({
  children,
  className = "",
  flat,
  interactive,
  selected,
  as: Tag = "div",
}: CardProps) {
  const classes = [
    "card",
    flat && "card--flat",
    interactive && "card--interactive",
    selected && "card--selected",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return <Tag className={classes}>{children}</Tag>;
}

interface CardHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  icon?: string;
  plain?: boolean;
}

export function CardHeader({ title, subtitle, actions, icon, plain }: CardHeaderProps) {
  return (
    <div className={`card__header ${plain ? "card__header--plain" : ""}`}>
      <div className="row row-3 grow">
        {icon ? (
          <span className="plan-leg__mode">
            <Icon name={icon} size={16} />
          </span>
        ) : null}
        <div className="grow">
          <div className="card__title">{title}</div>
          {subtitle ? <div className="card__subtitle">{subtitle}</div> : null}
        </div>
      </div>
      {actions ? <div className="row row-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({
  children,
  tight,
  flush,
  className = "",
}: {
  children: ReactNode;
  tight?: boolean;
  flush?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`card__body ${tight ? "card__body--tight" : ""} ${
        flush ? "card__body--flush" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function CardFooter({ children }: { children: ReactNode }) {
  return <div className="card__footer">{children}</div>;
}

/* --------------------------------------------------------------- banner */

export function Banner({
  tone = "info",
  icon,
  title,
  children,
  actions,
}: {
  tone?: "info" | "disrupted" | "risk" | "recovery" | "ontime";
  icon?: string;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className={`banner banner--${tone}`} role={tone === "disrupted" ? "alert" : undefined}>
      {icon ? <Icon name={icon} size={17} /> : null}
      <div className="grow">
        {title ? <div className="banner__title">{title}</div> : null}
        {children ? <div className="banner__body">{children}</div> : null}
      </div>
      {actions}
    </div>
  );
}

/* ----------------------------------------------------------------- stat */

export function Stat({
  label,
  value,
  detail,
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {detail ? <div className="stat__detail">{detail}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------ key/value */

export function KeyValue({
  items,
  wide,
}: {
  items: { label: ReactNode; value: ReactNode }[];
  wide?: boolean;
}) {
  return (
    <dl className={`kv ${wide ? "kv--wide" : ""}`}>
      {items.map((item, index) => (
        <div key={index} style={{ display: "contents" }}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function MetricRow({
  label,
  value,
  emphasis,
}: {
  label: ReactNode;
  value: ReactNode;
  emphasis?: boolean;
}) {
  return (
    <div className="metric-row">
      <span className="metric-row__label">{label}</span>
      <span className="metric-row__value" style={emphasis ? { fontSize: "var(--text-md)" } : undefined}>
        {value}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------ disclosure */

export function Disclosure({
  summary,
  children,
  defaultOpen,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="disclosure" open={defaultOpen}>
      <summary className="disclosure__summary">
        <span className="row row-2">{summary}</span>
        <Icon name="ChevronRight" size={16} className="disclosure__chevron" />
      </summary>
      <div className="disclosure__body">{children}</div>
    </details>
  );
}

/* --------------------------------------------------------------- divider */

export function Divider() {
  return <hr className="divider" />;
}
