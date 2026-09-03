export function amount(value: string | null | undefined): string {
  if (value === null || value === undefined) return "Unavailable";
  return `${value} USDT`;
}

export function time(value: string | null | undefined): string {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
