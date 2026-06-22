import type { Preview } from '@storybook/react';
import '../src/shared/styles/global.css';

const preview: Preview = {
  parameters: {
    controls: { expanded: true },
  },
};

export default preview;
