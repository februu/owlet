import {
  ActionIcon,
  Alert,
  AppShell,
  Badge,
  Box,
  Button,
  Center,
  Code,
  Container,
  CopyButton,
  Drawer,
  Grid,
  Group,
  Kbd,
  Loader,
  Modal,
  Paper,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure, useDocumentTitle, useHotkeys } from "@mantine/hooks";
import {
  IconAlertCircle,
  IconCheck,
  IconCopy,
  IconDownload,
  IconFileCode,
  IconHistory,
  IconMoon,
  IconPlayerPlay,
  IconPlayerStop,
  IconSun,
  IconTrash,
  IconWorld,
} from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { fetchInfo, runChecks, type Info, type Settings } from "./api";
import { download, ResultsPanel } from "./ResultsPanel";
import { applyEvent, countResults, isRunning, loadHistory, orderedResults, saveHistory, type Run } from "./run";
import { SettingsPanel } from "./SettingsPanel";
import { CountsInline, verdict } from "./status";
import { settingsToml } from "./toml";

export function App() {
  const [info, setInfo] = useState<Info | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [history, setHistory] = useState<Run[]>(loadHistory);
  const [historyOpen, historyHandlers] = useDisclosure(false);
  const [exportOpen, exportHandlers] = useDisclosure(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchInfo()
      .then((info) => {
        setInfo(info);
        setSettings(info.settings);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  const running = run !== null && isRunning(run);
  useDocumentTitle(run ? `${verdict(run).label} · ${hostname(run.target)} · Owlet` : "Owlet");

  const start = async () => {
    if (!info || !settings || running) return;
    const controller = new AbortController();
    abort.current = controller;
    const previous = run;
    let current: Run = {
      id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      version: info.version,
      target: settings.target,
      strict: settings.strict,
      checks: settings.active_checks,
      started_at: "",
      results: {},
    };
    setRunError(null);
    setRun(current);
    try {
      await runChecks(settings, (event) => setRun((current = applyEvent(current, event))), controller.signal);
      if (!current.finished && !current.error) current = { ...current, error: "The connection to owlet closed before the run finished." };
    } catch (e) {
      if (controller.signal.aborted) {
        current = { ...current, stopped: true };
      } else if (!current.started_at) {
        // Rejected before it started, e.g. an invalid URL or option: show why and keep the previous results.
        setRunError((e as Error).message);
        setRun(previous);
        return;
      } else {
        current = { ...current, error: (e as Error).message };
      }
    }
    setRun(current);
    setHistory((h) => saveHistory([current, ...h]));
  };

  useHotkeys([["mod+Enter", () => void start()]], []);

  if (loadError) {
    return (
      <Center h="100vh" p="md">
        <Alert color="red" icon={<IconAlertCircle />} title="Can't reach owlet" maw={480}>
          {loadError}. Is <Code>owlet-web</Code> running?
        </Alert>
      </Center>
    );
  }
  if (!info || !settings) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }

  return (
    <AppShell header={{ height: 60 }} padding="md">
      <AppShell.Header>
        <Container size="xl" h="100%">
          <Group h="100%" justify="space-between" wrap="nowrap">
            <Group gap="sm" wrap="nowrap">
              <OwlLogo />
              <Text fw={700} size="lg" style={{ letterSpacing: -0.3 }}>
                owlet
              </Text>
              <Badge variant="light" size="sm">
                v{info.version}
              </Badge>
              {info.config_path && (
                <Tooltip label={`Started with ${info.config_path}`}>
                  <Badge variant="default" size="sm" tt="none" leftSection={<IconFileCode size={12} />} visibleFrom="sm" className="mono">
                    {info.config_path.split(/[\\/]/).pop()}
                  </Badge>
                </Tooltip>
              )}
            </Group>
            <Group gap="xs" wrap="nowrap">
              <Button variant="default" size="xs" leftSection={<IconFileCode size={16} />} onClick={exportHandlers.open} visibleFrom="xs">
                Export config
              </Button>
              <ActionIcon variant="default" size="lg" onClick={exportHandlers.open} aria-label="Export config" hiddenFrom="xs">
                <IconFileCode size={18} />
              </ActionIcon>
              <Tooltip label="History">
                <ActionIcon variant="default" size="lg" onClick={historyHandlers.open} aria-label="History">
                  <IconHistory size={18} />
                </ActionIcon>
              </Tooltip>
              <ColorSchemeToggle />
            </Group>
          </Group>
        </Container>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="xl" py="md">
          <Paper withBorder radius="lg" p="md" mb="md" shadow="xs">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void start();
              }}
            >
              <Group wrap="nowrap" align="center">
                <TextInput
                  size="md"
                  style={{ flex: 1 }}
                  leftSection={<IconWorld size={18} />}
                  placeholder="https://example.com"
                  aria-label="Target URL"
                  value={settings.target}
                  onChange={(e) => setSettings({ ...settings, target: e.currentTarget.value })}
                />
                <Tooltip label="Treat warnings as failures">
                  <Box visibleFrom="sm">
                    <Switch label="Strict" checked={settings.strict} onChange={(e) => setSettings({ ...settings, strict: e.currentTarget.checked })} />
                  </Box>
                </Tooltip>
                {running ? (
                  <Button size="md" color="red" leftSection={<IconPlayerStop size={18} />} onClick={() => abort.current?.abort()}>
                    Stop
                  </Button>
                ) : (
                  <Tooltip label={<>Run <Kbd size="xs">Ctrl</Kbd> + <Kbd size="xs">Enter</Kbd></>}>
                    <Button
                      size="md"
                      type="submit"
                      leftSection={<IconPlayerPlay size={18} />}
                      disabled={!settings.target.trim() || !settings.active_checks.length}
                      variant="gradient"
                      gradient={{ from: "indigo", to: "violet", deg: 135 }}
                    >
                      Run
                    </Button>
                  </Tooltip>
                )}
              </Group>
            </form>
            {runError && (
              <Alert mt="md" color="red" icon={<IconAlertCircle />} title="Can't run" withCloseButton onClose={() => setRunError(null)}>
                {runError}
              </Alert>
            )}
          </Paper>

          <Grid gap="md">
            <Grid.Col span={{ base: 12, md: 5, lg: 4 }}>
              <SettingsPanel info={info} settings={settings} onChange={setSettings} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 7, lg: 8 }}>
              <ResultsPanel key={run?.id} run={run} />
            </Grid.Col>
          </Grid>
        </Container>
      </AppShell.Main>

      <HistoryDrawer
        opened={historyOpen}
        onClose={historyHandlers.close}
        history={history}
        currentId={run?.id}
        disabled={running}
        onSelect={(selected) => {
          setRun(selected);
          historyHandlers.close();
        }}
        onClear={() => setHistory(saveHistory([]))}
      />
      <ExportModal opened={exportOpen} onClose={exportHandlers.close} info={info} settings={settings} />
    </AppShell>
  );
}

function HistoryDrawer(props: {
  opened: boolean;
  onClose: () => void;
  history: Run[];
  currentId?: string;
  disabled: boolean;
  onSelect: (run: Run) => void;
  onClear: () => void;
}) {
  return (
    <Drawer opened={props.opened} onClose={props.onClose} position="right" title={<Text fw={600}>History</Text>} size="md">
      {props.history.length === 0 ? (
        <Text c="dimmed" size="sm">
          Finished runs appear here. They're kept in this browser.
        </Text>
      ) : (
        <Stack gap="xs">
          {props.history.map((run) => {
            const { label, color } = verdict(run);
            return (
              <UnstyledButton
                key={run.id}
                className="history-item"
                data-active={run.id === props.currentId || undefined}
                disabled={props.disabled}
                onClick={() => props.onSelect(run)}
              >
                <Group justify="space-between" wrap="nowrap" mb={6}>
                  <Text size="sm" fw={500} truncate>
                    {run.target}
                  </Text>
                  <Badge color={color} variant="light" size="sm" style={{ flexShrink: 0 }}>
                    {label}
                  </Badge>
                </Group>
                <Group gap={6}>
                  <Text size="xs" c="dimmed" mr={4}>
                    {run.started_at ? new Date(run.started_at).toLocaleString() : ""}
                  </Text>
                  <CountsInline counts={countResults(orderedResults(run))} />
                </Group>
              </UnstyledButton>
            );
          })}
          <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} onClick={props.onClear} mt="sm">
            Clear history
          </Button>
        </Stack>
      )}
    </Drawer>
  );
}

function ExportModal({ opened, onClose, info, settings }: { opened: boolean; onClose: () => void; info: Info; settings: Settings }) {
  const toml = settingsToml(settings, info.defaults);
  return (
    <Modal opened={opened} onClose={onClose} title={<Text fw={600}>Export as config.toml</Text>} size="lg">
      <Text size="sm" c="dimmed" mb="sm">
        Run it from the command line with <Code>uv run owlet config.toml</Code>.
        {info.config_path && " Plugins and headers from the original config file aren't included."}
      </Text>
      <Code block style={{ maxHeight: 420, overflow: "auto" }}>
        {toml}
      </Code>
      <Group justify="flex-end" mt="md">
        <CopyButton value={toml}>
          {({ copied, copy }) => (
            <Button variant="default" leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />} onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </Button>
          )}
        </CopyButton>
        <Button leftSection={<IconDownload size={16} />} onClick={() => download("config.toml", toml, "application/toml")}>
          Download
        </Button>
      </Group>
    </Modal>
  );
}

function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  return (
    <Tooltip label={scheme === "dark" ? "Light mode" : "Dark mode"}>
      <ActionIcon variant="default" size="lg" onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")} aria-label="Toggle color scheme">
        {scheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}

function OwlLogo() {
  return (
    <svg width={30} height={30} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="owl-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--mantine-color-indigo-6)" />
          <stop offset="1" stopColor="var(--mantine-color-violet-6)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#owl-bg)" />
      <path d="M6 7 L12 11 L7.5 13 Z M26 7 L20 11 L24.5 13 Z" fill="white" opacity="0.85" />
      <circle cx="11" cy="16" r="5" fill="white" />
      <circle cx="21" cy="16" r="5" fill="white" />
      <circle cx="11.6" cy="16.4" r="2.3" fill="#1e1b4b" />
      <circle cx="20.4" cy="16.4" r="2.3" fill="#1e1b4b" />
      <path d="M14.6 21 L17.4 21 L16 24 Z" fill="#fbbf24" />
    </svg>
  );
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
