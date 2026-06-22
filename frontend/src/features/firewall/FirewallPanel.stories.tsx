import type { Meta, StoryObj } from '@storybook/react';
import { FirewallPanel } from './FirewallPanel';

const meta: Meta<typeof FirewallPanel> = {
  title: 'Monitor/FirewallPanel',
  component: FirewallPanel,
};

export default meta;

type Story = StoryObj<typeof FirewallPanel>;

export const Overrides: Story = {
  args: {
    initialData: {
      enabled: true,
      overrides: [
        { override_id: 'override-1', scope_type: 'global', reason: 'manual review window', expires_at: '2026-06-03T11:00:00Z' },
      ],
      override_audit: [{ audit_id: 'audit-1', override_id: 'override-1', action: 'create', actor: 'monitor' }],
    },
  },
};
