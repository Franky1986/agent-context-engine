import type { Meta, StoryObj } from '@storybook/react';
import { StoragePanel } from './StoragePanel';

const meta: Meta<typeof StoragePanel> = {
  title: 'Monitor/StoragePanel',
  component: StoragePanel,
};

export default meta;

type Story = StoryObj<typeof StoragePanel>;

export const Healthy: Story = {
  args: {
    initialData: {
      ok: true,
      database_path: 'memory/agent-memory.sqlite3',
      size_bytes: 7340032,
      tables: [{ name: 'events' }, { name: 'sessions' }, { name: 'dream_runs' }],
    },
  },
};
