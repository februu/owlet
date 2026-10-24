import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  Collapse,
  Group,
  Indicator,
  NumberInput,
  Paper,
  Stack,
  Switch,
  Tabs,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import {
  IconAdjustmentsHorizontal,
  IconArrowBackUp,
  IconChevronDown,
  IconListCheck,
  IconLock,
  IconSettings,
} from "@tabler/icons-react";
import { useState } from "react";
import type { CheckInfo, CheckOption, Info, Settings } from "./api";

const TIMEOUT_KEY = "timeout_seconds";

interface Props {
  info: Info;
  settings: Settings;
  onChange: (settings: Settings) => void;
}

export function SettingsPanel({ info, settings, onChange }: Props) {
  const active = new Set(settings.active_checks);
  return (
    <Paper withBorder p="md" radius="lg">
      <Tabs defaultValue="checks" variant="pills" radius="md">
        <Tabs.List mb="md" style={{ flexWrap: "nowrap" }}>
            <Tabs.Tab value="checks" leftSection={<IconListCheck size={16} />}>
              Checks{" "}
              <Badge size="xs" variant="light" ml={4} circle={false}>
                {active.size}/{info.checks.length}
              </Badge>
            </Tabs.Tab>
            <Tabs.Tab value="settings" leftSection={<IconSettings size={16} />}>
              Settings
            </Tabs.Tab>
            <Tooltip label={info.config_path ? "Reset to the config file" : "Reset to defaults"}>
              <ActionIcon variant="subtle" color="gray" ml="auto" my="auto" onClick={() => onChange(info.settings)} aria-label="Reset settings">
                <IconArrowBackUp size={18} />
              </ActionIcon>
            </Tooltip>
          </Tabs.List>

        <Tabs.Panel value="checks">
          <ChecksList info={info} settings={settings} onChange={onChange} />
        </Tabs.Panel>
        <Tabs.Panel value="settings">
          <GeneralSettings info={info} settings={settings} onChange={onChange} />
        </Tabs.Panel>
      </Tabs>
    </Paper>
  );
}

function ChecksList({ info, settings, onChange }: Props) {
  const active = new Set(settings.active_checks);
  const groups = new Map<string, CheckInfo[]>();
  for (const check of info.checks) groups.set(check.group, [...(groups.get(check.group) ?? []), check]);

  const toggle = (name: string, on: boolean) =>
    onChange({
      ...settings,
      // Keep the existing output order and add newly enabled checks at the end, as they would be in active_checks.
      active_checks: on ? [...settings.active_checks, name] : settings.active_checks.filter((n) => n !== name),
    });

  const setOption = (check: string, key: string, value: unknown) => {
    const table = { ...settings.checks[check] };
    if (value === undefined) delete table[key];
    else table[key] = value;
    const checks = { ...settings.checks, [check]: table };
    if (!Object.keys(table).length) delete checks[check];
    onChange({ ...settings, checks });
  };

  return (
    <Stack gap="md">
      <Group gap="xs">
        <Button size="compact-xs" variant="default" onClick={() => onChange({ ...settings, active_checks: info.checks.map((c) => c.name) })}>
          Select all
        </Button>
        <Button size="compact-xs" variant="default" onClick={() => onChange({ ...settings, active_checks: [] })}>
          Select none
        </Button>
      </Group>
      {[...groups].map(([group, checks]) => (
        <Stack key={group} gap={4}>
          <Text size="xs" fw={600} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.6 }}>
            {group}
          </Text>
          {checks.map((check) => (
            <CheckRow
              key={check.name}
              check={check}
              active={active.has(check.name)}
              values={settings.checks[check.name] ?? {}}
              globalTimeout={settings.check_timeout_seconds}
              onToggle={(on) => toggle(check.name, on)}
              onOption={(key, value) => setOption(check.name, key, value)}
            />
          ))}
        </Stack>
      ))}
    </Stack>
  );
}

interface CheckRowProps {
  check: CheckInfo;
  active: boolean;
  values: Record<string, unknown>;
  globalTimeout: number;
  onToggle: (on: boolean) => void;
  onOption: (key: string, value: unknown) => void;
}

function CheckRow({ check, active, values, globalTimeout, onToggle, onOption }: CheckRowProps) {
  const [open, setOpen] = useState(false);
  const changed = Object.keys(values).length > 0;
  return (
    <Box className="check-row" px="xs" py={6}>
      <Group wrap="nowrap" align="flex-start" gap="sm">
        <Checkbox mt={3} checked={active} onChange={(e) => onToggle(e.currentTarget.checked)} aria-label={check.name} />
        <Box style={{ flex: 1, minWidth: 0, cursor: "pointer" }} onClick={() => onToggle(!active)}>
          <Text size="sm" fw={500} className="mono" c={active ? undefined : "dimmed"}>
            {check.name}
          </Text>
          {check.description && (
            <Text size="xs" c="dimmed" lineClamp={open ? undefined : 2}>
              <InlineCode text={check.description} />
            </Text>
          )}
        </Box>
        <Tooltip label={changed ? "Options (changed)" : "Options"}>
          <Indicator disabled={!changed} size={7} offset={4}>
            <ActionIcon variant="subtle" color="gray" onClick={() => setOpen((o) => !o)} aria-label={`Options for ${check.name}`}>
              {open ? <IconChevronDown size={16} /> : <IconAdjustmentsHorizontal size={16} />}
            </ActionIcon>
          </Indicator>
        </Tooltip>
      </Group>
      <Collapse expanded={open}>
        <Stack gap="xs" pl={34} pt="xs" pb={4}>
          {check.options.map((option) => (
            <OptionInput key={option.name} option={option} value={values[option.name]} onChange={(v) => onOption(option.name, v)} />
          ))}
          <NumberInput
            size="xs"
            label={<span className="mono">{TIMEOUT_KEY}</span>}
            description="How long this check may run"
            placeholder={`${globalTimeout} (global)`}
            min={0.1}
            step={5}
            suffix=" s"
            value={(values[TIMEOUT_KEY] as number | undefined) ?? ""}
            onChange={(v) => onOption(TIMEOUT_KEY, typeof v === "number" ? v : undefined)}
          />
        </Stack>
      </Collapse>
    </Box>
  );
}

/** Docstring text with `backticked` parts as inline code. */
function InlineCode({ text }: { text: string }) {
  return text.split(/`([^`]+)`/).map((part, i) => (i % 2 ? <Code key={i} fz="inherit">{part}</Code> : part));
}

/** An input for one check option, chosen by its type. Setting it back to the default removes it, so exports stay minimal. */
function OptionInput({ option, value, onChange }: { option: CheckOption; value: unknown; onChange: (value: unknown) => void }) {
  const set = (v: unknown) => onChange(JSON.stringify(v) === JSON.stringify(option.default) ? undefined : v);
  const current = value ?? option.default;
  const label = <span className="mono">{option.name}</span>;
  const description = `${option.type}, default ${JSON.stringify(option.default)}`;

  switch (option.type) {
    case "int":
    case "float":
      return (
        <NumberInput
          size="xs"
          label={label}
          description={description}
          allowDecimal={option.type === "float"}
          value={current as number}
          onChange={(v) => (typeof v === "number" ? set(v) : onChange(undefined))}
        />
      );
    case "bool":
      return <Switch size="sm" label={label} description={description} checked={Boolean(current)} onChange={(e) => set(e.currentTarget.checked)} />;
    case "str":
      return <TextInput size="xs" label={label} description={description} value={String(current)} onChange={(e) => set(e.currentTarget.value)} />;
  }
  if (option.type.startsWith("list[")) {
    return <TagsInput size="xs" label={label} description={description} value={(current as string[]).map(String)} onChange={set} />;
  }
  return <JsonOptionInput label={label} description={description} value={current} onChange={set} />;
}

/** Fallback for option types the panel has no input for: edit the value as JSON. */
function JsonOptionInput({ label, description, value, onChange }: { label: React.ReactNode; description: string; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(JSON.stringify(value));
  const [error, setError] = useState<string | null>(null);
  return (
    <TextInput
      size="xs"
      classNames={{ input: "mono" }}
      label={label}
      description={`${description} (as JSON)`}
      value={text}
      error={error}
      onChange={(e) => {
        setText(e.currentTarget.value);
        try {
          onChange(JSON.parse(e.currentTarget.value));
          setError(null);
        } catch {
          setError("Not valid JSON");
        }
      }}
    />
  );
}

function GeneralSettings({ info, settings, onChange }: Props) {
  const setHttp = (http: Partial<Settings["http"]>) => onChange({ ...settings, http: { ...settings.http, ...http } });
  const defaults = info.defaults;
  return (
    <Stack gap="sm">
      <NumberInput
        label="Check timeout"
        description="How long one check may run before it's stopped and reported as FAIL"
        suffix=" s"
        min={0.1}
        step={5}
        value={settings.check_timeout_seconds}
        onChange={(v) => onChange({ ...settings, check_timeout_seconds: typeof v === "number" ? v : defaults.check_timeout_seconds })}
      />
      <Text size="xs" fw={600} c="dimmed" tt="uppercase" mt="sm" style={{ letterSpacing: 0.6 }}>
        HTTP client
      </Text>
      <NumberInput
        label="Request timeout"
        description="For each network step: connecting, sending, waiting for data"
        suffix=" s"
        min={0.1}
        step={1}
        value={settings.http.timeout_seconds}
        onChange={(v) => setHttp({ timeout_seconds: typeof v === "number" ? v : defaults.http.timeout_seconds })}
      />
      <TextInput
        label="User-Agent"
        description="Set a browser-like value if the site blocks owlet"
        classNames={{ input: "mono" }}
        value={settings.http.user_agent}
        onChange={(e) => setHttp({ user_agent: e.currentTarget.value })}
      />
      <NumberInput
        label="Max connections"
        description="Most connections open at once, across all checks"
        min={1}
        allowDecimal={false}
        value={settings.http.max_connections}
        onChange={(v) => setHttp({ max_connections: typeof v === "number" ? v : defaults.http.max_connections })}
      />
      <Switch
        mt="xs"
        label="Verify TLS certificates"
        description="ssl_certificate always verifies, so it still reports the certificate"
        checked={settings.http.verify}
        onChange={(e) => setHttp({ verify: e.currentTarget.checked })}
      />
      {info.header_names.length > 0 && (
        <Box mt="xs">
          <Group gap={6} mb={6}>
            <IconLock size={14} />
            <Text size="sm" fw={500}>
              Headers from the config file
            </Text>
          </Group>
          <Group gap={6}>
            {info.header_names.map((name) => (
              <Badge key={name} variant="default" className="mono" tt="none">
                {name}
              </Badge>
            ))}
          </Group>
          <Text size="xs" c="dimmed" mt={6}>
            Values stay on the server. Edit them in the config file.
          </Text>
        </Box>
      )}
    </Stack>
  );
}
