import type { Meta, StoryObj } from '@storybook/react';
import { RiskDetailPanel } from './RiskDetailPanel';

const meta: Meta<typeof RiskDetailPanel> = {
  title: 'Monitor/RiskDetailPanel',
  component: RiskDetailPanel,
};

export default meta;

type Story = StoryObj<typeof RiskDetailPanel>;

export const Detail: Story = {
  args: {
    initialData: {
      risk_event: {
        risk_event_id: 'risk-1',
        status: 'blocked',
        risk_level: 'medium',
        decision: 'block',
        reason: 'Side-effect-capable action follows prior sensitive or quarantined context and requires explicit user approval.',
        impact: 'May execute a decision derived from tainted or sensitive context.',
        tool_name: 'Bash',
        created_at: '2026-06-03T10:00:00Z',
        source_kind: 'tool_input',
        categories: ['approval_required'],
        poisoning_flags: ['tainted_context_side_effect'],
        approval_line: 'approve risk-1 nonce_demo',
        command_ref: 'monitor:risk_events:risk-1',
        taint_context: [
          {
            risk_event_id: 'risk-source-1',
            status: 'quarantined',
            risk_level: 'medium',
            reason: 'Classifier output was not valid JSON or did not match the risk schema.',
          },
        ],
      },
      evidence: [{ type: 'command' }],
      overrides: [],
      classifier: {
        run: {
          runner: 'cursor',
          status: 'succeeded_fallback_auth_required',
          model: 'gpt-5.4-mini-medium',
          duration_ms: 420,
          total_tokens: 310,
          error: 'Cursor classifier runner requires login and fell back to deterministic policy.',
        },
      },
    },
  },
};
