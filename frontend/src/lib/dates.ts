export const day = (value: string | Date) => new Date(value).toDateString();
export function dateLabel(value: string) {
  const today = new Date(), yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  return day(value) === day(today) ? "Today" : day(value) === day(yesterday) ? "Yesterday" : new Date(value).toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "short", day: "numeric" });
}
