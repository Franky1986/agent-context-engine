import type { Meta, StoryObj } from '@storybook/react';
import { SessionsPanel } from './SessionsPanel';

const meta = {
  title: 'Monitor/Sessions Panel',
  component: SessionsPanel,
} satisfies Meta<typeof SessionsPanel>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Recent: Story = {
  args: {
    initialData: {
      total: 2,
      sessions: [
        {
          session_id: 's_001',
          thread_name: 'Structure migration',
          project_id: 'agent-memory',
          client_type: 'cursor',
          cwd: '/Users/frankrichter/projects/agent-context-engine',
          last_workdir: '/Users/frankrichter/projects/pr-llm-service',
          preferred_dream_runner: 'claude',
          dream_runner_used: 'claude',
          summary_status: 'summarized',
          dream_status: 'succeeded',
        },
        { session_id: 's_002', thread_name: 'Monitor pilot', project_id: 'agent-memory', client_type: 'codex', summary_status: 'summary_pending', dream_status: 'dream_pending' },
      ],
    },
  },
};
