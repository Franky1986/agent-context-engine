import type { Meta, StoryObj } from '@storybook/react';
import { DreamArtifactsPanel } from './DreamArtifactsPanel';

const meta: Meta<typeof DreamArtifactsPanel> = {
  title: 'Monitor/DreamArtifactsPanel',
  component: DreamArtifactsPanel,
};

export default meta;

type Story = StoryObj<typeof DreamArtifactsPanel>;

export const Evaluation: Story = {
  args: {
    initialEvaluation: {
      runs: [
        { dream_run_id: 'dream-a', status: 'completed', pipeline_status: 'persisted' },
        { dream_run_id: 'dream-b', status: 'failed', pipeline_status: 'failed', error: 'invalid graph patch' },
      ],
    },
    initialGraph: {
      entities: [{ semantic_entity_id: 'entity-a', name: 'Monitor' }],
      relations: [{ semantic_relation_id: 'relation-a', relation_type: 'USES' }],
    },
    selectedDream: {
      dream_run_id: 'dream-a',
      session_id: 'session-a',
      status: 'succeeded',
      pipeline_status: 'persisted',
      runner: 'codex',
      runner_model: 'gpt-5.4-mini',
      started_at: '2026-06-03T10:00:00Z',
      finished_at: '2026-06-03T10:00:42Z',
      duration_ms: 42000,
      total_tokens: 14220,
      input_event_count: 6,
      episode_short: 'The dream consolidates monitor navigation and writes a compact semantic summary for the operator cockpit.',
      v2_deterministic_entities: [{ key: 'monitor', name: 'Monitor', type: 'product' }],
      v2_deterministic_relations: [{ type: 'tracks', from: { type: 'session', key: 'session-a' }, to: { type: 'task', key: 'ux-epic' } }],
      v2_semantic_entities: [{ key: 'entity-a', name: 'Monitor UX Epic', type: 'task', confidence: 0.94, properties: { summary: 'Epic for monitor UX / IA consolidation.' }, mutations: [{ mutation_kind: 'created' }] }],
      v2_semantic_relations: [{ type: 'tracks', from: { key: 'session-a' }, to: { key: 'ux-epic' }, confidence: 0.88, properties: { summary: 'Session tracks the epic.' }, mutations: [{ mutation_kind: 'updated' }] }],
      v2_reconciliation_decisions: [{ action: 'created', decision: 'created', confidence: 0.91 }],
      v2_review_items: [],
      v2_stages: [
        {
          stage_name: 'dream_narrative',
          stage_order: 1,
          label: 'Dream Narrative',
          category: 'llm_call',
          badge: 'LLM sees/produces',
          status: 'succeeded',
          runner: 'codex',
          model: 'gpt-5.4-mini',
          total_tokens: 5000,
          duration_ms: 12000,
          files: [{ kind: 'prompt', path: 'memory/dream/v2/runs/dream-a/01-dream-narrative/prompt.md', content: '## Current Deterministic Handover\nA short handover exists.' }],
        },
      ],
    },
  },
};
