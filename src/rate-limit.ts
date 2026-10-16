import { randomInt } from "node:crypto";

const MIN_PAUSE_MS = 2_000;
const MAX_PAUSE_MS = 5_000;

export function pause(): Promise<void> {
  const duration = randomInt(MIN_PAUSE_MS, MAX_PAUSE_MS + 1);
  return new Promise((resolvePause) => setTimeout(resolvePause, duration));
}
