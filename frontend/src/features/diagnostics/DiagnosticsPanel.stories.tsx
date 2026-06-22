import type { Meta, StoryObj } from '@storybook/react';
import { DiagnosticsPanel } from './DiagnosticsPanel';

const meta: Meta<typeof DiagnosticsPanel> = {
  title: 'Monitor/DiagnosticsPanel',
  component: DiagnosticsPanel,
};

export default meta;

type Story = StoryObj<typeof DiagnosticsPanel>;

export const Runtime: Story = {
  args: {
    initialData: {
      ok: true,
      exit_code: 0,
      lines: [
        'ok  runtime pipeline version: 2',
        'ok  runtime dream interval seconds: 900',
        'ok  runtime neo4j database: agent_memory',
        'ok  sqlite db: memory/status/agent-memory.sqlite3',
      ],
    },
  },
};
