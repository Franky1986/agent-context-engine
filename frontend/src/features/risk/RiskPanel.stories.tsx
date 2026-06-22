import type { Meta, StoryObj } from '@storybook/react';
import { RiskPanel } from './RiskPanel';

const meta = {
  title: 'Monitor/Risk Panel',
  component: RiskPanel,
} satisfies Meta<typeof RiskPanel>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Recent: Story = {
  args: {
    initialData: {
      total: 2,
      risks: [
        { risk_event_id: 'risk_001', status: 'warned', risk_level: 'medium', tool_name: 'shell', reason: 'filesystem write in project', created_at: '2026-06-03T12:00:00+00:00' },
        { risk_event_id: 'risk_002', status: 'blocked', risk_level: 'high', tool_name: 'shell', reason: 'destructive command outside policy', created_at: '2026-06-03T12:05:00+00:00' },
      ],
    },
  },
};
