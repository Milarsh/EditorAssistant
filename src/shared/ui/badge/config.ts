import type { ClassNameValue } from 'tailwind-merge'

export enum BadgeVariant {
  Primary = 'primary',
  Secondary = 'secondary',
}

export const variantColorMap: Record<BadgeVariant, ClassNameValue> = {
  [BadgeVariant.Primary]: 'bg-blue-500',
  [BadgeVariant.Secondary]: 'bg-red-500',
}
