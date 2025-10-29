import '../src/app/styles/index.css'

import { INITIAL_VIEWPORTS } from '@storybook/addon-viewport'
import type { Preview } from '@storybook/react'

const preview: Preview = {
  parameters: {
    layout: 'fullscreen',

    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },

    viewport: {
      viewports: INITIAL_VIEWPORTS,
      defaultViewport: 'iphone14promax',
    },

    backgrounds: {
      default: 'dark',
    },
  },
  tags: ['autodocs'],
}

export default preview
