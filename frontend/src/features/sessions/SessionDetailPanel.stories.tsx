import type { Meta, StoryObj } from '@storybook/react';
import { SessionDetailPanel } from './SessionDetailPanel';

const meta: Meta<typeof SessionDetailPanel> = {
  title: 'Monitor/SessionDetailPanel',
  component: SessionDetailPanel,
};

export default meta;

type Story = StoryObj<typeof SessionDetailPanel>;

export const Timeline: Story = {
  args: {
    initialData: {
      session: {
        session_id: 'session-a',
        thread_name: 'Hexagonal refactor',
        client_type: 'codex',
        project_id: 'agent-memory',
        activity_status: 'active',
        summary_status: 'summarized',
        dream_status: 'dreamed',
        latest_activity_summary: 'OpenAPI erweitert und Monitor-Operatorflächen konsolidiert.',
      },
      summary: {
        summary_kind: 'handover',
        created_at: '2026-06-03T10:05:00Z',
        input_event_count: 8,
        content: 'Der Refactor ist stabil. Offene Arbeit liegt jetzt im Monitor UX und in der Session-first Journey.',
      },
      dreams: [{
        dream_run_id: 'dream-a',
        status: 'succeeded',
        runner: 'codex',
        runner_model: 'gpt-5.4-mini',
        total_tokens: 12450,
        started_at: '2026-06-03T10:04:00Z',
        episode_short: 'Der Dream konsolidiert die neue Monitor-Navigation und gruppiert Inspect, Firewall und Storage um die neue IA.',
        v2_deterministic_entities: [{ key: 'session-a', name: 'Session A', type: 'session' }],
        v2_deterministic_relations: [{ type: 'contains', from: { type: 'session', key: 'session-a' }, to: { type: 'task', key: 'ux-epic' } }],
        v2_semantic_entities: [{ entity_key: 'ux-epic', name: 'Monitor UX Epic', entity_type: 'task', summary: 'Epic for monitor UX / IA consolidation.' }],
        v2_semantic_relations: [{ relation_key: 'rel-1', relation_type: 'tracks', source_entity_key: 'session-a', target_entity_key: 'ux-epic', summary: 'Session tracks the UX epic.' }],
        v2_reconciliation_decisions: [{ decision: 'created' }],
      }],
      events: [
        { event_id: 'event-1', kind: 'user', created_at: '2026-06-03T10:00:00Z', preview: 'Plan ausführen' },
        { event_id: 'event-2', kind: 'tool', created_at: '2026-06-03T10:02:00Z', preview: 'OpenAPI erweitert' },
      ],
    },
  },
};
