// Pill label for the "how far from clearing the gate" number exposed by the
// backend as `distance_to_clear`. Bands let a human skim the master list
// without reading digits: "close", "+0.NN", "very far".
export function formatDistance(distance: number): string {
  if (distance <= 0) return 'cleared';
  if (distance < 1.0) return `+${distance.toFixed(2)}`;
  if (distance < 2.0) return 'far';
  return 'very far';
}
