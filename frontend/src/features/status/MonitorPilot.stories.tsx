import type { Meta, StoryObj } from '@storybook/react';
import { MonitorPilot } from './MonitorPilot';

const meta = {
  title: 'Monitor/Status Pilot',
  component: MonitorPilot,
} satisfies Meta<typeof MonitorPilot>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Healthy: Story = {
  args: {
    initialStatus: {
      ok: true,
      generated_at: '2026-06-03T12:00:00+00:00',
      sessions: 128,
      events: 3420,
      pending_dreams: 3,
    },
    initialFirewall: {
      enabled: true,
      source: 'monitor',
      overrides: [],
      override_audit: [],
    },
  },
};

export const WithOverrides: Story = {
  args: {
    initialStatus: {
      ok: true,
      sessions: 128,
      events: 3420,
      pending_dreams: 7,
    },
    initialFirewall: {
      enabled: false,
      reason: 'maintenance window',
      overrides: [
        {
          override_id: 'fwovr_demo',
          scope_type: 'workdir',
          reason: 'temporary local migration',
          expires_at: '2026-06-03T13:00:00+00:00',
        },
      ],
      override_audit: [],
    },
  },
};
