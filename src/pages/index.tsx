import { Badge } from '@/shared/ui/badge'
import { BadgeVariant } from '@/shared/ui/badge/config'

export const MainPage = () => {
  return (
    <main className="flex-center flex min-h-screen">
      <div className="vertical flex-center">
        <h1 className="text-2xl font-bold text-black">Main page</h1>
        <div className="horizontal gap-x-4">
          <Badge>kek</Badge>
          <Badge variant={BadgeVariant.Secondary}>aboba</Badge>
        </div>
      </div>
    </main>
  )
}
