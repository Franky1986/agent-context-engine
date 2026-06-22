import type { Meta, StoryObj } from '@storybook/react';
import { KnowledgeFocusPanel } from './KnowledgeFocusPanel';

const meta: Meta<typeof KnowledgeFocusPanel> = {
  title: 'Monitor/KnowledgeFocusPanel',
  component: KnowledgeFocusPanel,
};

export default meta;

type Story = StoryObj<typeof KnowledgeFocusPanel>;

export const FocusedContext: Story = {
  args: {
    initialData: {
      nodes: [
        { id: 'entity-1', label: 'Monitor UX Epic', type: 'Task' },
        { id: 'entity-2', label: 'Sessions', type: 'Feature' },
        { id: 'entity-3', label: 'Dreams', type: 'Feature' },
        { id: 'entity-4', label: 'Knowledge', type: 'Feature' },
      ],
      edges: [
        { id: 'edge-1', source: 'entity-1', target: 'entity-2', type: 'TRACKS' },
        { id: 'edge-2', source: 'entity-1', target: 'entity-3', type: 'SHAPES' },
        { id: 'edge-3', source: 'entity-1', target: 'entity-4', type: 'CENTERS' },
      ],
    },
    focusTarget: { kind: 'entity', id: 'entity-1', label: 'Monitor UX Epic' },
  },
};
