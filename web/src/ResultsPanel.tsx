import {
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Code,
  Collapse,
  EmptyState,
  Group,
  Loader,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconBug, IconChevronDown, IconChevronRight, IconClock, IconDownload, IconWorld } from "@tabler/icons-react";
import { useState } from "react";
import { STATUSES, type ResultJson, type Status } from "./api";
import { countResults, isRunning, orderedResults, runJson, type Run } from "./run";
import { STATUS_META, StatusBadge, StatusIcon, verdict, worstStatus } from "./status";

export function ResultsPanel({ run }: { run: Run | null }) {
  const [filter, setFilter] = useState<Status | null>(null);

  if (!run) {
    return (
      <Paper withBorder radius="lg" p="xl" h="100%">
        <EmptyState
          mt="xl"
          icon={<IconWorld size={28} />}
          title="No run yet"
          description="Enter a URL, pick your checks and press Run. Results stream in as each check finishes."
        />
      </Paper>
    );
  }

  const results = orderedResults(run);
  const counts = countResults(results);
  const done = run.checks.filter((check) => run.results[check]).length;
  const running = isRunning(run);
  const { label, color } = verdict(run);
  const shownChecks = run.checks.filter((check) => !filter || run.results[check]?.some((r) => r.status === filter));

  return (
    <Stack gap="md">
      <Paper withBorder radius="lg" p="lg">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box style={{ minWidth: 0 }}>
            <Group gap="xs" mb={4}>
              <Badge color={color} variant="filled" size="lg" leftSection={running ? <Loader size={10} color="white" /> : undefined}>
                {label}
              </Badge>
              {run.strict && (
                <Badge variant="outline" color="gray">
                  strict
                </Badge>
              )}
            </Group>
            <Title order={3} style={{ overflowWrap: "anywhere" }}>
              <Anchor href={run.target} target="_blank" rel="noreferrer" inherit c="inherit">
                {run.target}
              </Anchor>
            </Title>
            <Group gap="md" mt={4}>
              <Text size="sm" c="dimmed">
                {run.started_at ? new Date(run.started_at).toLocaleString() : "Starting…"}
              </Text>
              {run.finished && (
                <Group gap={4}>
                  <IconClock size={14} color="var(--mantine-color-dimmed)" />
                  <Text size="sm" c="dimmed">
                    {run.finished.duration_seconds.toFixed(2)}s
                  </Text>
                </Group>
              )}
              {run.finished && (
                <Text size="sm" c="dimmed">
                  exit code <Code>{run.finished.exit_code}</Code>
                </Text>
              )}
            </Group>
          </Box>
          <Button
            variant="default"
            leftSection={<IconDownload size={16} />}
            style={{ flexShrink: 0 }}
            disabled={running}
            onClick={() => download(`owlet-${new URL(run.target).hostname}.json`, runJson(run))}
          >
            JSON
          </Button>
        </Group>

        <Progress
          mt="lg"
          size="sm"
          radius="xl"
          value={run.checks.length ? (done / run.checks.length) * 100 : 0}
          animated={running}
          color={running ? "indigo" : color}
          transitionDuration={300}
        />
        <Text size="xs" c="dimmed" mt={6}>
          {done} of {run.checks.length} checks finished
        </Text>

        <SimpleGrid cols={{ base: 3, sm: 5 }} spacing="sm" mt="lg">
          {STATUSES.map((status) => (
            <StatTile
              key={status}
              status={status}
              count={counts[status]}
              active={filter === status}
              onClick={() => setFilter(filter === status ? null : status)}
            />
          ))}
        </SimpleGrid>
      </Paper>

      {run.error && (
        <Alert color="grape" icon={<IconBug />} title="Owlet crashed outside a check" radius="lg">
          <Code block>{run.error}</Code>
        </Alert>
      )}

      {filter && (
        <Group gap="xs">
          <Text size="sm" c="dimmed">
            Showing only <b>{filter}</b> results.
          </Text>
          <Anchor size="sm" component="button" onClick={() => setFilter(null)}>
            Show all
          </Anchor>
        </Group>
      )}

      {shownChecks.map((check) => (
        <CheckCard
          key={check}
          name={check}
          results={(run.results[check] ?? []).filter((r) => !filter || r.status === filter)}
          pending={!run.results[check]}
          running={running}
        />
      ))}
    </Stack>
  );
}

function StatTile({ status, count, active, onClick }: { status: Status; count: number; active: boolean; onClick: () => void }) {
  const { color, label } = STATUS_META[status];
  return (
    <UnstyledButton onClick={onClick} aria-pressed={active}>
      <Paper
        withBorder
        p="sm"
        radius="md"
        className="stat-tile"
        data-active={active || undefined}
        data-empty={count === 0 || undefined}
        style={{ "--tile-color": `var(--mantine-color-${color}-filled)` }}
      >
        <Group justify="space-between" wrap="nowrap">
          <Text fz={26} fw={650} lh={1}>
            {count}
          </Text>
          <StatusIcon status={status} size={26} />
        </Group>
        <Text size="xs" c="dimmed" mt={6}>
          {label}
        </Text>
      </Paper>
    </UnstyledButton>
  );
}

function CheckCard({ name, results, pending, running }: { name: string; results: ResultJson[]; pending: boolean; running: boolean }) {
  const worst = worstStatus(results.map((r) => r.status));
  const duration = results[0]?.duration_seconds;
  return (
    <Paper
      withBorder
      radius="lg"
      p="md"
      className="check-card"
      style={{ "--stripe": worst ? `var(--mantine-color-${STATUS_META[worst].color}-filled)` : undefined }}
    >
      <Group justify="space-between" mb={pending ? 0 : "xs"}>
        <Text fw={600} className="mono" size="sm">
          {name}
        </Text>
        {pending ? (
          running ? (
            <Group gap={6}>
              <Loader size={12} />
              <Text size="xs" c="dimmed">
                Running…
              </Text>
            </Group>
          ) : (
            <Text size="xs" c="dimmed">
              Didn't finish
            </Text>
          )
        ) : (
          duration != null && (
            <Text size="xs" c="dimmed">
              {duration < 1 ? `${Math.round(duration * 1000)} ms` : `${duration.toFixed(2)} s`}
            </Text>
          )
        )}
      </Group>
      <Stack gap={4}>
        {results.map((result, i) => (
          <ResultRow key={i} result={result} />
        ))}
      </Stack>
    </Paper>
  );
}

function ResultRow({ result }: { result: ResultJson }) {
  const hasData = Object.keys(result.data).length > 0;
  const expandable = result.details.length > 0 || hasData || result.traceback != null;
  // Problems open by default, so their details are visible without a click.
  const [open, setOpen] = useState(result.fails_run || result.status === "WARN");
  const Chevron = open ? IconChevronDown : IconChevronRight;
  return (
    <Box>
      <UnstyledButton
        onClick={() => expandable && setOpen((o) => !o)}
        style={{ width: "100%", cursor: expandable ? "pointer" : "default" }}
        className="check-row"
        px={6}
        py={4}
      >
        <Group wrap="nowrap" gap="sm" align="flex-start">
          <StatusBadge status={result.status} />
          <Text size="sm" style={{ flex: 1, minWidth: 0 }}>
            {result.name && (
              <Text span fw={600} className="mono" size="sm" mr={6}>
                {result.name}
              </Text>
            )}
            {result.summary}
          </Text>
          {expandable && <Chevron size={16} color="var(--mantine-color-dimmed)" style={{ flexShrink: 0, marginTop: 2 }} />}
        </Group>
      </UnstyledButton>
      {expandable && (
        <Collapse expanded={open}>
          <Stack gap={6} pl={78} pr={6} pt={4} pb={6} style={{ minWidth: 0 }}>
            {result.details.length > 0 && (
              <Box component="ul" m={0} pl="md">
                {result.details.map((line, i) => (
                  <Text component="li" key={i} size="xs" className="mono" style={{ wordBreak: "break-all" }}>
                    {line}
                  </Text>
                ))}
              </Box>
            )}
            {hasData && <Code block style={{ overflowX: "auto" }}>{JSON.stringify(result.data, null, 2)}</Code>}
            {result.traceback && (
              <Code block color="var(--mantine-color-grape-light)" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                {result.traceback}
              </Code>
            )}
          </Stack>
        </Collapse>
      )}
    </Box>
  );
}

export function download(filename: string, text: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  link.click();
  URL.revokeObjectURL(url);
}
