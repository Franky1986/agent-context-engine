import type { Meta, StoryObj } from '@storybook/react';
import { DreamsPanel } from './DreamsPanel';

const meta: Meta<typeof DreamsPanel> = {
  title: 'Monitor/DreamsPanel',
  component: DreamsPanel,
};

export default meta;

type Story = StoryObj<typeof DreamsPanel>;

export const RecentRuns: Story = {
  args: {
    initialData: {
      total: 2,
      dreams: [
        {
          dream_run_id: 'dream-1',
          session_id: 'session-a',
          status: 'completed',
          runner: 'codex',
          created_at: '2026-06-03T10:00:00Z',
          episode_short: 'Monitor navigation and operator cockpit were consolidated into the new IA.',
          v2_deterministic_entities: [{ key: 'monitor' }],
          v2_semantic_entities: [{ key: 'ux-epic' }],
        },
        {
          dream_run_id: 'dream-2',
          session_id: 'session-b',
          status: 'failed',
          runner: 'codex',
          created_at: '2026-06-03T10:10:00Z',
          error: 'missing graph patch',
          episode_short: 'The dream failed while producing the graph patch.',
          v2_deterministic_entities: [],
          v2_semantic_entities: [],
        },
      ],
    },
  },
};
