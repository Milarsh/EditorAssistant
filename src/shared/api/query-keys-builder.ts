import type { AxiosResponse } from 'axios'

import { createQueryFunction } from './query-functions-builder.ts'

export type HttpClientMethod<Response, Filters extends [...any]> = (
  ...filters: Filters
) => Promise<AxiosResponse<Response>>

/**
 * Utility for building React Query `queryKey` + `queryFn` pairs
 * from a given HTTP client method.
 *
 * @example
 * ```ts
 * import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
 * import { createQueryKeys } from '@lukemorales/query-key-factory'
 * import { httpClient } from '@/shared/api/http-client'
 * import { createKeys } from '@/shared/api/query-keys-builder'
 *
 * export const userQueryKeys = createQueryKeys('user', {
 *   info: createKeys(httpClient.users.getUsersMeGet),
 * })
 *
 * export const useUserInfo = () => useQuery(userQueryKeys.info())
 *
 * export const useUpdateUserInfo = () => {
 *   const queryClient = useQueryClient()
 *
 *   return useMutation({
 *     mutationFn: () => httpClient.user.updateUserInfoPatch({ name: 'Jonh' }),
 *     onSettled: () => {
 *       queryClient.invalidateQueries({
 *         queryKey: userQueryKeys.info().queryKey,
 *       })
 *     },
 *   })
 * }
 * ```
 */
export function createKeys<Response, Params extends any[]>(
  httpClientMethod: HttpClientMethod<Response, Params>,
) {
  return (...params: Params) => {
    return {
      queryKey: params.slice(0, httpClientMethod.length) as [any],
      queryFn: createQueryFunction(httpClientMethod, ...params),
    }
  }
}
