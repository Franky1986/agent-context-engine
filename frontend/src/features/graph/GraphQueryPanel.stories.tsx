import type { Meta, StoryObj } from '@storybook/react';
import { GraphQueryPanel } from './GraphQueryPanel';

const meta: Meta<typeof GraphQueryPanel> = {
  title: 'Monitor/GraphQueryPanel',
  component: GraphQueryPanel,
};

export default meta;

type Story = StoryObj<typeof GraphQueryPanel>;

export const SearchResult: Story = {
  args: {
    initialQuery: 'monitor',
    initialData: {
      nodes: [
        { id: 'node-1', label: 'Monitor', type: 'Feature' },
        { id: 'node-2', label: 'OpenAPI', type: 'Contract' },
      ],
      edges: [
        { id: 'edge-1', source: 'node-1', target: 'node-2', type: 'USES' },
      ],
    },
  },
};
