// Types and calls for the API in owlet/web/server.py.

export const STATUSES = ["PASS", "WARN", "FAIL", "SKIP", "ERROR"] as const;
export type Status = (typeof STATUSES)[number];
export type Counts = Record<Status, number>;

export interface CheckOption {
  name: string;
  /** The parameter's annotation as Python writes it, e.g. `int`, `float` or `list[str]`. */
  type: string;
  default: unknown;
}

export interface CheckInfo {
  name: string;
  /** The module the check comes from, e.g. `tls`. */
  group: string;
  description: string | null;
  options: CheckOption[];
}

export interface HttpSettings {
  timeout_seconds: number;
  user_agent: string;
  verify: boolean;
  max_connections: number;
}

/** Run settings, in the shape of a TOML config file. */
export interface Settings {
  target: string;
  active_checks: string[];
  strict: boolean;
  check_timeout_seconds: number;
  /** [checks.<name>] tables: options that differ from their defaults, and `timeout_seconds`. */
  checks: Record<string, Record<string, unknown>>;
  http: HttpSettings;
}

export interface Info {
  version: string;
  config_path: string | null;
  checks: CheckInfo[];
  /** From the config file the server was started with, or the defaults without one. */
  settings: Settings;
  defaults: Settings;
  /** Headers the config file sends. Their values stay on the server. */
  header_names: string[];
}

/** One result, as in `owlet --json`. */
export interface ResultJson {
  check: string;
  name: string | null;
  status: Status;
  summary: string;
  details: string[];
  data: Record<string, unknown>;
  duration_seconds: number | null;
  fails_run: boolean;
  traceback: string | null;
}

export type RunEvent =
  | { type: "start"; target: string; strict: boolean; checks: string[]; started_at: string }
  | { type: "check"; check: string; results: ResultJson[] }
  | { type: "done"; exit_code: number; duration_seconds: number; summary: Counts }
  | { type: "error"; error: string };

export async function fetchInfo(): Promise<Info> {
  const response = await fetch("/api/info");
  if (!response.ok) throw new Error(`Couldn't load checks: HTTP ${response.status}`);
  return response.json();
}

/** Run checks with `settings`, calling `onEvent` as each event streams in. Rejects with the server's message for invalid settings. */
export async function runChecks(settings: Settings, onEvent: (event: RunEvent) => void, signal: AbortSignal): Promise<void> {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
    signal,
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error ?? `HTTP ${response.status}`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffered = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffered += value;
    const lines = buffered.split("\n");
    buffered = lines.pop() ?? "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
  }
}

export function emptyCounts(): Counts {
  return { PASS: 0, WARN: 0, FAIL: 0, SKIP: 0, ERROR: 0 };
}
