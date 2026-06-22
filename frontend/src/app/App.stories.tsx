import type { Meta, StoryObj } from '@storybook/react';
import { App } from './App';

const meta = {
  title: 'App/Shell',
  component: App,
} satisfies Meta<typeof App>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};
