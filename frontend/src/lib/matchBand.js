/**
 * One place that decides what a match percentage *means*, so the card badge and
 * the detail panel can never disagree with each other.
 *
 * The band label is not decoration: the colour scale runs green→amber→red, a
 * pair deuteranopes cannot separate by hue, so the number and this text always
 * travel with it.
 */
export function matchBand(pct) {
  if (pct >= 75) return { key: 'strong', label: 'Strong match' }
  if (pct >= 50) return { key: 'partial', label: 'Partial match' }
  return { key: 'weak', label: 'Weak match' }
}
