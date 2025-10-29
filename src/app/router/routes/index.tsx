import { createFileRoute } from '@tanstack/react-router'

import { MainPage } from '@/pages'

export const Route = createFileRoute('/')({
  component: MainPage,
})
