import { Badge, ThemeIcon } from "@mantine/core";
import {
  IconAlertTriangle,
  IconBug,
  IconCircleCheck,
  IconCircleX,
  IconPlayerSkipForward,
  type Icon,
} from "@tabler/icons-react";
import type { Counts, Status } from "./api";
import { isRunning, type Run } from "./run";

export const STATUS_META: Record<Status, { color: string; icon: Icon; label: string }> = {
  PASS: { color: "teal", icon: IconCircleCheck, label: "Passed" },
  WARN: { color: "yellow", icon: IconAlertTriangle, label: "Warnings" },
  FAIL: { color: "red", icon: IconCircleX, label: "Failed" },
  SKIP: { color: "gray", icon: IconPlayerSkipForward, label: "Skipped" },
  ERROR: { color: "grape", icon: IconBug, label: "Errors" },
};

/** Most severe first, to pick the status a check's card is colored by. */
const SEVERITY: Status[] = ["ERROR", "FAIL", "WARN", "PASS", "SKIP"];

export function worstStatus(statuses: Status[]): Status | undefined {
  return SEVERITY.find((status) => statuses.includes(status));
}

export function StatusBadge({ status }: { status: Status }) {
  return (
    <Badge color={STATUS_META[status].color} variant="light" w={64} radius="sm" className="mono">
      {status}
    </Badge>
  );
}

export function StatusIcon({ status, size = 22 }: { status: Status; size?: number }) {
  const { color, icon: Icon } = STATUS_META[status];
  return (
    <ThemeIcon color={color} variant="light" size={size} radius="xl">
      <Icon size={size * 0.65} stroke={2} />
    </ThemeIcon>
  );
}

/** The run's outcome in a word, with its color. */
export function verdict(run: Run): { label: string; color: string } {
  if (run.error) return { label: "Crashed", color: "grape" };
  if (run.stopped) return { label: "Stopped", color: "gray" };
  if (isRunning(run)) return { label: "Running", color: "indigo" };
  return run.finished?.exit_code === 0 ? { label: "Healthy", color: "teal" } : { label: "Failing", color: "red" };
}

export function CountsInline({ counts }: { counts: Counts }) {
  const shown = SEVERITY.filter((status) => counts[status]);
  return (
    <>
      {shown.map((status) => (
        <Badge key={status} size="xs" variant="dot" color={STATUS_META[status].color}>
          {counts[status]} {status.toLowerCase()}
        </Badge>
      ))}
    </>
  );
}
