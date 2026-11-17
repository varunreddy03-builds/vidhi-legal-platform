/**
 * Date/money formatting used everywhere in the UI.
 *
 * Dates are always shown as "10 Jun 2026" - never 10/6/2026, which means 10 June in India and
 * 6 October in the US. The server sends UTC timestamps without a "Z" (Mongo drops the zone), and
 * JavaScript would read those as local time, so we pin them to UTC here.
 */

const DATE = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const DATE_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

const ISO_DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DATETIME_NO_ZONE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "string") {
    const dateOnly = ISO_DATE_ONLY.exec(value.trim());
    if (dateOnly) {
      // A calendar date has no time zone: build it locally so it can never slip to the day before.
      return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
    }
    const s = value.trim();
    const d = new Date(ISO_DATETIME_NO_ZONE.test(s) ? `${s.replace(" ", "T")}Z` : s);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "10 Jun 2026", or an em dash when there is no usable date. */
export function formatDate(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  return d ? DATE.format(d) : "—";
}

/** "10 Jun 2026, 3:05 pm". */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  return d ? DATE_TIME.format(d).replace(/\bam\b/i, "am").replace(/\bpm\b/i, "pm") : "—";
}

/**
 * For free-text dates (e.g. read out of a proof by the AI): reformat only when the text is an
 * unambiguous ISO date; otherwise show it exactly as written rather than guess day vs month.
 */
export function formatDateText(text: string | null | undefined): string {
  if (!text) return "";
  return ISO_DATE_ONLY.test(text.trim()) ? formatDate(text) : text;
}

/** "₹5,000" / "$49" - amount with the right symbol for its ISO currency code. */
export function formatMoney(amount: number, currency: string): string {
  const code = (currency || "INR").toUpperCase();
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: code,
      maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    }).format(amount);
  } catch {
    return `${amount.toLocaleString("en-IN")} ${code}`;
  }
}
