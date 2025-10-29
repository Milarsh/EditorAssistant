import { DEVTOOLS_CONFIG } from '../config/devtools.ts'

export const initializeApp = async (): Promise<unknown> => {
  if (DEVTOOLS_CONFIG.eruda) {
    const { default: eruda } = await import('eruda')

    eruda.init()
  }

  if (DEVTOOLS_CONFIG.reactScan) {
    const { scan } = await import('react-scan')

    scan()
  }

  return Promise.resolve()
}
