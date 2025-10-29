import type { AxiosResponse } from 'axios'

type HttpClientMethodType<T> = (...args: any) => Promise<AxiosResponse<T>>

export function createQueryFunction<T, TParams extends any[]>(
  httpClientMethod: HttpClientMethodType<T>,
  ...params: TParams
) {
  return async (): Promise<T> => {
    const response = await httpClientMethod(...params)

    return response.data
  }
}
