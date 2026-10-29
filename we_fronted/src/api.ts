export type MenuRecord = {
  id: number
  name: string
  path: string
  parent_id?: number | null
}

export type MenuSection = MenuRecord & {
  items: MenuRecord[]
}

export type User = {
  user_id: number
  username: string
}

export type DataLabel = '正向' | '中性' | '负向'

export type DataItem = {
  id: string
  content: string
  fields: Record<string, unknown>
  label: string | null
  labeled_by: string | null
  inserted_at: string | null
  labeled_at: string | null
}

export type DataItemsPage = {
  items: DataItem[]
  total: number
  page: number
  page_size: number
}

export type LabelStatusFilter =
  | 'all'
  | 'labeled'
  | 'unlabeled'
  | DataLabel

type ApiResponse<T> = {
  code: number
  message: string
  data: T
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers,
      credentials: 'include',
    })
  } catch {
    throw new ApiError('无法连接服务器，请检查后端服务是否已启动。', 0)
  }

  let result: ApiResponse<T>
  try {
    result = (await response.json()) as ApiResponse<T>
  } catch {
    throw new ApiError(`服务器返回了无法识别的响应（HTTP ${response.status}）。`, response.status)
  }

  if (!response.ok || result.code !== 0) {
    throw new ApiError(result.message || `请求失败（HTTP ${response.status}）。`, response.status)
  }
  return result.data
}

export function login(username: string, password: string): Promise<User> {
  return request<User>('/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function getCurrentUser(signal?: AbortSignal): Promise<User> {
  return request<User>('/auth/me', { signal })
}

export function logout(): Promise<null> {
  return request<null>('/logout', { method: 'POST' })
}

export async function getMenuSections(
  signal?: AbortSignal,
): Promise<MenuSection[]> {
  const parents = await request<MenuRecord[]>('/menus', { signal })
  return Promise.all(
    parents.map(async (parent) => ({
      ...parent,
      items: await request<MenuRecord[]>(`/menus/${parent.id}/children`, {
        signal,
      }),
    })),
  )
}

export function getDataItems(
  page: number,
  pageSize: number,
  labelStatus: LabelStatusFilter,
  signal?: AbortSignal,
): Promise<DataItemsPage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    label_status: labelStatus,
  })
  return request<DataItemsPage>(`/data-items?${query}`, { signal })
}

export function getDataItem(
  itemId: string,
  signal?: AbortSignal,
): Promise<DataItem> {
  return request<DataItem>(`/data-items/${encodeURIComponent(itemId)}`, {
    signal,
  })
}

export function saveDataItemLabel(
  itemId: string,
  label: DataLabel,
): Promise<Pick<DataItem, 'id' | 'label' | 'labeled_by' | 'labeled_at'>> {
  return request<Pick<DataItem, 'id' | 'label' | 'labeled_by' | 'labeled_at'>>(
    `/data-items/${encodeURIComponent(itemId)}/label`,
    {
      method: 'PUT',
      body: JSON.stringify({ label }),
    },
  )
}
