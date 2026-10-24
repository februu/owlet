import { emptyCounts, type Counts, type ResultJson, type RunEvent } from "./api";

/** A run as the panel tracks it, built up from the streamed events. Kept in history after it ends. */
export interface Run {
  id: string;
  version: string;
  target: string;
  strict: boolean;
  /** Checks in output order. */
  checks: string[];
  started_at: string;
  /** Results per check, filled in as each check finishes. */
  results: Record<string, ResultJson[]>;
  finished?: { exit_code: number; duration_seconds: number; summary: Counts };
  /** Owlet crashed outside a check, or the connection failed. */
  error?: string;
  stopped?: boolean;
}

export function applyEvent(run: Run, event: RunEvent): Run {
  switch (event.type) {
    case "start":
      return { ...run, target: event.target, strict: event.strict, checks: event.checks, started_at: event.started_at };
    case "check":
      return { ...run, results: { ...run.results, [event.check]: event.results } };
    case "done":
      return { ...run, finished: { exit_code: event.exit_code, duration_seconds: event.duration_seconds, summary: event.summary } };
    case "error":
      return { ...run, error: event.error };
  }
}

export function isRunning(run: Run): boolean {
  return !run.finished && !run.error && !run.stopped;
}

/** Results in output order: by check as listed, then as each check produced them. */
export function orderedResults(run: Run): ResultJson[] {
  return run.checks.flatMap((check) => run.results[check] ?? []);
}

export function countResults(results: ResultJson[]): Counts {
  const counts = emptyCounts();
  for (const result of results) counts[result.status]++;
  return counts;
}

/** The run as `owlet --json` prints it, for downloading. */
export function runJson(run: Run): string {
  const results = orderedResults(run);
  return JSON.stringify(
    {
      owlet_version: run.version,
      target: run.target,
      strict: run.strict,
      started_at: run.started_at,
      duration_seconds: run.finished?.duration_seconds ?? null,
      exit_code: run.finished?.exit_code ?? null,
      summary: countResults(results),
      results,
    },
    null,
    2,
  );
}

const HISTORY_KEY = "owlet:history";
const HISTORY_LIMIT = 20;

export function loadHistory(): Run[] {
  try {
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]");
    return Array.isArray(stored) ? stored : [];
  } catch {
    return [];
  }
}

export function saveHistory(history: Run[]): Run[] {
  const kept = history.slice(0, HISTORY_LIMIT);
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(kept));
  } catch {
    // Storage is full or blocked: history just won't survive a reload.
  }
  return kept;
}
