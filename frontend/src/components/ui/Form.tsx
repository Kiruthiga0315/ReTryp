import type { ReactNode } from "react";
import { useId } from "react";
import { Icon } from "./Icon";

/* ---------------------------------------------------------------- field */

interface FieldProps {
  label: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  children: ReactNode;
}

export function Field({ label, htmlFor, hint, error, required, children }: FieldProps) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={htmlFor}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      {children}
      {error ? (
        <span className="field__error" role="alert">
          <Icon name="TriangleAlert" size={12} />
          {error}
        </span>
      ) : hint ? (
        <span className="field__hint">{hint}</span>
      ) : null}
    </div>
  );
}

interface TextFieldProps {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "password" | "tel" | "date" | "number";
  placeholder?: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  disabled?: boolean;
  autoComplete?: string;
  inputMode?: "text" | "email" | "tel" | "numeric" | "decimal";
}

export function TextField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  hint,
  error,
  required,
  disabled,
  autoComplete,
  inputMode,
}: TextFieldProps) {
  const id = useId();
  return (
    <Field label={label} htmlFor={id} hint={hint} error={error} required={required}>
      <input
        id={id}
        className="input"
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        autoComplete={autoComplete}
        inputMode={inputMode}
        aria-invalid={error ? true : undefined}
        aria-required={required || undefined}
      />
    </Field>
  );
}

interface SelectFieldProps {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  hint?: ReactNode;
  error?: string | null;
  disabled?: boolean;
  placeholder?: string;
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  hint,
  error,
  disabled,
  placeholder,
}: SelectFieldProps) {
  const id = useId();
  return (
    <Field label={label} htmlFor={id} hint={hint} error={error}>
      <select
        id={id}
        className="select"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function CheckboxField({
  label,
  checked,
  onChange,
  hint,
  disabled,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div>
      <label className="checkbox" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          disabled={disabled}
        />
        <span>
          {label}
          {hint ? <span className="field__hint" style={{ display: "block" }}>{hint}</span> : null}
        </span>
      </label>
    </div>
  );
}

/* -------------------------------------------------------------- search */

export function SearchInput({
  value,
  onChange,
  placeholder = "Search",
  ariaLabel = "Search",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
}) {
  return (
    <div className="search-box">
      <input
        className="input input--search"
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
      />
    </div>
  );
}

/* --------------------------------------------------------------- tabs */

interface TabsProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  tabs: { value: T; label: string; count?: number; icon?: string }[];
  ariaLabel: string;
}

export function Tabs<T extends string>({ value, onChange, tabs, ariaLabel }: TabsProps<T>) {
  return (
    <div className="tabs" role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          className="tab"
          aria-selected={value === tab.value}
          onClick={() => onChange(tab.value)}
        >
          {tab.icon ? <Icon name={tab.icon} size={15} /> : null}
          {tab.label}
          {tab.count !== undefined ? <span className="tab__count">{tab.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

/* --------------------------------------------------------- pagination */

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  noun = "items",
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  noun?: string;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) {
    return (
      <div className="pagination">
        <span className="muted">
          {total} {noun}
        </span>
      </div>
    );
  }
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);

  const pages: number[] = [];
  const start = Math.max(1, Math.min(page - 2, pageCount - 4));
  for (let index = start; index < start + 5 && index <= pageCount; index += 1) pages.push(index);

  return (
    <div className="pagination">
      <span className="muted">
        {first}–{last} of {total} {noun}
      </span>
      <div className="pagination__pages">
        <button
          type="button"
          className="page-btn"
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          <Icon name="ChevronLeft" size={14} />
        </button>
        {pages.map((number) => (
          <button
            key={number}
            type="button"
            className="page-btn"
            aria-current={number === page ? "true" : undefined}
            onClick={() => onPage(number)}
          >
            {number}
          </button>
        ))}
        <button
          type="button"
          className="page-btn"
          onClick={() => onPage(page + 1)}
          disabled={page >= pageCount}
          aria-label="Next page"
        >
          <Icon name="ChevronRight" size={14} />
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------ sortable header */

export function SortHeader<T extends string>({
  field,
  label,
  sort,
  onSort,
  numeric,
}: {
  field: T;
  label: ReactNode;
  sort: { field: T; direction: "asc" | "desc" };
  onSort: (field: T) => void;
  numeric?: boolean;
}) {
  const active = sort.field === field;
  return (
    <th
      className={`is-sortable ${numeric ? "is-numeric" : ""}`}
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        className="sort-indicator"
        data-active={active}
        onClick={() => onSort(field)}
        style={{ background: "none", border: 0, padding: 0, cursor: "pointer", font: "inherit", color: "inherit", letterSpacing: "inherit", textTransform: "inherit" }}
      >
        {label}
        <Icon
          name={active ? (sort.direction === "asc" ? "ChevronUp" : "ChevronDown") : "ChevronsUpDown"}
          size={13}
        />
      </button>
    </th>
  );
}

/* ---------------------------------------------------------- filter bar */

export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="filter-bar">{children}</div>;
}
