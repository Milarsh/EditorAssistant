import type { Meta, StoryObj } from '@storybook/react'

import { BadgeVariant } from './config.ts'
import { Badge } from './ui.tsx'

const meta: Meta<typeof Badge> = {
  title: 'shared/ui/badge',
  component: Badge,
  argTypes: {
    variant: {
      control: 'select',
      options: Object.values(BadgeVariant),
    },
  },
}

type Story = StoryObj<typeof Badge>

export const Primary: Story = {
  args: {
    variant: BadgeVariant.Primary,
    children: 'Primary Badge',
  },
}

export const Secondary: Story = {
  args: {
    variant: BadgeVariant.Secondary,
    children: 'Secondary Badge',
  },
}

export default meta
