export const IS_DEVELOPMENT = import.meta.env.MODE === 'development'
export const IS_PRODUCTION = import.meta.env.MODE === 'production'
export const IS_STAGING = import.meta.env.MODE === 'staging'

export const API_URL = import.meta.env.VITE_API_URL as string
