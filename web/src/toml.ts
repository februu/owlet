import type { Settings } from "./api";

/** Settings as a config.toml owlet can run, leaving out [http] keys that match `defaults`. */
export function settingsToml(settings: Settings, defaults: Settings): string {
  const lines = [
    `target = ${value(settings.target)}`,
    `strict = ${value(settings.strict)}`,
    `check_timeout_seconds = ${value(settings.check_timeout_seconds)}`,
    "",
    "active_checks = [",
    ...settings.active_checks.map((name) => `    ${value(name)},`),
    "]",
  ];
  const http = Object.entries(settings.http).filter(([key, v]) => v !== defaults.http[key as keyof Settings["http"]]);
  if (http.length) lines.push("", "[http]", ...http.map(([key, v]) => `${key} = ${value(v)}`));
  for (const [name, options] of Object.entries(settings.checks)) {
    const entries = Object.entries(options);
    if (entries.length) lines.push("", `[checks.${name}]`, ...entries.map(([key, v]) => `${key} = ${value(v)}`));
  }
  return lines.join("\n") + "\n";
}

function value(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(value).join(", ")}]`;
  // JSON strings are valid TOML basic strings, and JSON numbers and booleans are valid TOML too.
  return JSON.stringify(v);
}
