import { API_URL } from '../config'
import { Api } from './api.ts'

export const httpClient = new Api({
  baseURL: API_URL,
})
