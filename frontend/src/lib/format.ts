/** Formatting helpers. Times arrive from the API pre-formatted in the local
 *  zone (for example "28 Sep 2026 15:00 CEST"); these helpers cover the rest. */

const CURRENCY_SYMBOLS: Record<string, string> = {
  EUR: "€",
  USD: "$",
  GBP: "£",
  INR: "₹",
  CHF: "CHF ",
};

/** Resolve the currency a signed-in user should see, mirroring the backend
 *  order: Settings currency, then budget currency, then the product default
 *  (INR). */
export function displayCurrencyFor(user: {
  settings?: { currency?: string | null } | null;
  budget_currency?: string | null;
} | null | undefined): string {
  const preferred = (user?.settings?.currency ?? "").toUpperCase();
  if (preferred) return preferred;
  const budget = (user?.budget_currency ?? "").toUpperCase();
  return budget || "INR";
}

export function money(minor: number | null | undefined, currency: string): string {
  if (minor === null || minor === undefined) return "—";
  const symbol = CURRENCY_SYMBOLS[currency];
  const amount = (minor / 100).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (symbol) return `${symbol}${amount}`;
  return `${currency} ${amount}`;
}

export function moneySigned(minor: number, currency: string): string {
  if (minor === 0) return money(0, currency);
  return `${minor > 0 ? "+" : "−"}${money(Math.abs(minor), currency)}`;
}

export function duration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  const sign = minutes < 0 ? "−" : "";
  const abs = Math.abs(minutes);
  const days = Math.floor(abs / 1440);
  const hours = Math.floor((abs % 1440) / 60);
  const mins = abs % 60;
  const parts: string[] = [];
  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  if (mins || parts.length === 0) parts.push(`${mins}m`);
  return `${sign}${parts.join(" ")}`;
}

export function signedDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || minutes === 0) return "—";
  return `${minutes > 0 ? "+" : "−"}${duration(Math.abs(minutes))}`;
}

/** "Arrives 1h 20m earlier" / "Arrives 4h 30m later" / "Arrives as planned". */
export function arrivalPhrase(deltaMinutes: number): string {
  if (deltaMinutes === 0) return "Arrives as planned";
  const word = deltaMinutes > 0 ? "later" : "earlier";
  return `Arrives ${duration(Math.abs(deltaMinutes))} ${word}`;
}

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** Short clock time from a pre-formatted local string: "28 Sep 2026 15:00 CEST" -> "15:00". */
export function clockFromLocal(local: string): string {
  const match = local.match(/(\d{1,2}:\d{2})/);
  return match ? match[1] : local;
}

/** Zone suffix from a pre-formatted local string: "28 Sep 2026 15:00 CEST" -> "CEST". */
export function zoneFromLocal(local: string): string {
  const parts = local.trim().split(/\s+/);
  const last = parts[parts.length - 1] ?? "";
  return /^[A-Z]{2,5}$/.test(last) ? last : "";
}

export function dateFromLocal(local: string): string {
  // "28 Sep 2026 15:00 CEST" -> "28 Sep 2026"
  const match = local.match(/^(.+?)\s+\d{1,2}:\d{2}/);
  return match ? match[1] : local;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function pluralise(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? `${singular}s`);
}

/** Relative time for notification and audit timestamps. */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffSeconds = Math.round((Date.now() - then) / 1000);
  const abs = Math.abs(diffSeconds);
  const suffix = diffSeconds >= 0 ? "ago" : "from now";
  if (abs < 45) return "just now";
  if (abs < 3600) return `${Math.round(abs / 60)} min ${suffix}`;
  if (abs < 86400) return `${Math.round(abs / 3600)} h ${suffix}`;
  return `${Math.round(abs / 86400)} d ${suffix}`;
}

export function riskLabel(level: string): string {
  return { low: "Low risk", medium: "Medium risk", high: "High risk" }[level] ?? titleCase(level);
}

export function changesLabel(count: number): string {
  if (count === 0) return "No changes";
  return `${count} ${pluralise(count, "change")}`;
}
