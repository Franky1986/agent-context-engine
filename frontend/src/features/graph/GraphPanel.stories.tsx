import type { Meta, StoryObj } from '@storybook/react';
import { GraphPanel } from './GraphPanel';

const meta: Meta<typeof GraphPanel> = {
  title: 'Monitor/GraphPanel',
  component: GraphPanel,
};

export default meta;

type Story = StoryObj<typeof GraphPanel>;

export const Overview: Story = {
  args: {
    initialOptions: { entity_types: ['Session', 'Topic'], relation_types: ['MENTIONS', 'FOLLOWS'] },
    initialEntities: {
      total: 2,
      entities: [
        { entity_id: 'entity-1', name: 'Hexagonal Refactor', type: 'Topic', last_seen_at: '2026-06-03T10:00:00Z' },
        { entity_id: 'entity-2', name: 'Monitor', type: 'Feature', last_seen_at: '2026-06-03T10:05:00Z' },
      ],
    },
    initialRelations: {
      total: 1,
      relations: [
        { relation_id: 'rel-1', source_name: 'Monitor', target_name: 'OpenAPI', type: 'USES' },
      ],
    },
  },
};
