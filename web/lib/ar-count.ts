/** Arabic count phrases with correct number agreement: 1 singular+واحد, 2 dual, 3-10 plural, 11+ accusative singular. */
export interface ArNoun {
  one: string; // e.g. "فحص"
  two: string; // "فحصان"
  few: string; // "فحوص"
  many: string; // "فحصًا"
}

export const CHECKS: ArNoun = { one: "فحص", two: "فحصان", few: "فحوص", many: "فحصًا" };
export const DOMAINS: ArNoun = { one: "نطاق", two: "نطاقان", few: "نطاقات", many: "نطاقًا" };

export function arCount(n: number, noun: ArNoun): string {
  const c = Math.max(0, Math.round(n));
  if (c === 1) return `${noun.one} واحد`;
  if (c === 2) return noun.two;
  if (c >= 3 && c <= 10) return `${c} ${noun.few}`;
  return `${c} ${noun.many}`;
}

/** "N linked checks" in Arabic with agreement: فحص واحد مرتبط، فحصان مرتبطان، 5 فحوص مرتبطة، 12 فحصًا مرتبطًا. */
export function arLinkedChecks(n: number): string {
  const c = Math.max(0, Math.round(n));
  if (c === 1) return "فحص واحد مرتبط";
  if (c === 2) return "فحصان مرتبطان";
  return `${arCount(c, CHECKS)} ${c >= 3 && c <= 10 ? "مرتبطة" : "مرتبطًا"}`;
}
