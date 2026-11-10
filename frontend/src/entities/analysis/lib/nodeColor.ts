export function nodeColor(value: number, min: number, max: number): string {
  const ratio = max > min ? (value - min) / (max - min) : 1;
  return `hsl(${Math.round(220 * (1 - ratio))}, 80%, 45%)`;
}
