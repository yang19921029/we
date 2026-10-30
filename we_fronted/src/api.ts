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
  role?: string
}

export type PlatformUser = {
  id: number
  username: string
  role: string
}

export type DataLabel = string

export type MultimodalAnnotationItem = {
  kind: 'bbox' | 'polygon' | 'keypoint' | 'segment'
  label: string
  media_url: string
  points?: Array<{ x: number; y: number }>
  start?: number
  end?: number
}

export type MultimodalAnnotation = {
  items: MultimodalAnnotationItem[]
}

export type DataItem = {
  id: string
  content: string
  fields: Record<string, unknown>
  annotation: MultimodalAnnotation | null
  label: string | null
  labeled_by: string | null
  inserted_at: string | null
  labeled_at: string | null
}

export type LabelHistoryEntry = {
  label: DataLabel | null
  labeled_by: string
  labeled_at: string
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

export type DatasetRecord = {
  id: number
  name: string
  description: string
  record_count: number
  created_by: string
  created_at: string
  project_id: number
  project_name: string
}

export type OrganizationRecord = {
  id: number
  name: string
  description: string
}

export type ProjectRecord = {
  id: number
  name: string
  description: string
  organization_id: number
  organization_name: string
}

export type ProjectMember = PlatformUser & {
  created_at: string
  added_by: string
}

export type LabelOption = {
  code: string
  name: string
  color: string
}

export type LabelSchema = {
  id: number
  name: string
  description: string
  labels: LabelOption[]
  version: number
  updated_by: string
  updated_at: string
}

export type AnnotationTask = {
  id: number
  name: string
  dataset_id: number
  dataset_name: string
  project_id: number
  project_name: string
  label_schema_id: number
  label_schema_name: string
  assignee: string
  priority: '高' | '中' | '低'
  status: string
  deadline: string | null
  instructions: string
  created_by: string
  created_at: string
  total_items: number
  labeled_items: number
}

export type PlatformStatistics = {
  total: number
  labeled: number
  unlabeled: number
  completion_rate: number
  reviewed: number
  overdue_tasks: number
  labels: Array<{ name: string; count: number }>
  annotators: Array<{ name: string; count: number }>
}

export type ReviewItem = {
  items: DataItem[]
  total: number
}

export type QualityCheckResult = {
  passed: boolean
  warnings: string[]
}

export type AuditLog = {
  id: number
  actor: string
  action: string
  entity_type: string
  entity_id: string
  details: Record<string, unknown>
  created_at: string
}

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
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
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
  datasetId?: number,
  searchText = '',
  sortBy: 'newest' | 'uncertain' = 'newest',
  taskId?: number,
): Promise<DataItemsPage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    label_status: labelStatus,
    q: searchText,
    sort: sortBy,
  })
  if (datasetId !== undefined) query.set('dataset_id', String(datasetId))
  if (taskId !== undefined) query.set('task_id', String(taskId))
  return request<DataItemsPage>(`/data-items?${query}`, { signal })
}

export function getDatasets(signal?: AbortSignal): Promise<DatasetRecord[]> {
  return request('/datasets', { signal })
}

export function getOrganizations(signal?: AbortSignal): Promise<OrganizationRecord[]> {
  return request('/organizations', { signal })
}

export function createOrganization(
  name: string,
  description: string,
): Promise<OrganizationRecord> {
  return request('/organizations', {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  })
}

export function getProjects(signal?: AbortSignal): Promise<ProjectRecord[]> {
  return request('/projects', { signal })
}

export function createProject(input: {
  name: string
  description: string
  organization_id: number
}): Promise<ProjectRecord> {
  return request('/projects', { method: 'POST', body: JSON.stringify(input) })
}

export function getProjectMembers(
  projectId: number,
  signal?: AbortSignal,
): Promise<ProjectMember[]> {
  return request(`/projects/${projectId}/members`, { signal })
}

export function addProjectMember(
  projectId: number,
  userId: number,
): Promise<PlatformUser> {
  return request(`/projects/${projectId}/members`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  })
}

export function removeProjectMember(
  projectId: number,
  userId: number,
): Promise<{ user_id: number }> {
  return request(`/projects/${projectId}/members/${userId}`, {
    method: 'DELETE',
  })
}

export function createDataset(
  name: string,
  description: string,
  projectId = 1,
): Promise<DatasetRecord> {
  return request('/datasets', {
    method: 'POST',
    body: JSON.stringify({ name, description, project_id: projectId }),
  })
}

export function importDatasetFile(
  datasetId: number,
  file: File,
): Promise<{ dataset_id: number; imported_count: number }> {
  const body = new FormData()
  body.set('file', file)
  return request(`/datasets/${datasetId}/import`, { method: 'POST', body })
}

export function getLabelSchemas(
  signal?: AbortSignal,
): Promise<LabelSchema[]> {
  return request('/label-schemas', { signal })
}

export function getLabelSchemaVersions(
  schemaId: number,
  signal?: AbortSignal,
): Promise<Array<{ version: number; changed_by: string; changed_at: string; labels: LabelOption[] }>> {
  return request(`/label-schemas/${schemaId}/versions`, { signal })
}

export function createLabelSchema(
  name: string,
  description: string,
  labels: LabelOption[],
): Promise<Pick<LabelSchema, 'id' | 'name' | 'description' | 'labels' | 'version'>> {
  return request('/label-schemas', {
    method: 'POST',
    body: JSON.stringify({ name, description, labels }),
  })
}

export function updateLabelSchema(
  schemaId: number,
  description: string,
  labels: LabelOption[],
): Promise<{ id: number; labels: LabelOption[]; version: number }> {
  return request(`/label-schemas/${schemaId}`, {
    method: 'PUT',
    body: JSON.stringify({ description, labels }),
  })
}

export function getAnnotationTasks(
  signal?: AbortSignal,
): Promise<AnnotationTask[]> {
  return request('/tasks', { signal })
}

export function createAnnotationTask(input: {
  name: string
  dataset_id: number
  label_schema_id: number
  assignee: string
  priority: AnnotationTask['priority']
  deadline: string
  instructions: string
}): Promise<Pick<AnnotationTask, 'id' | 'name' | 'dataset_id' | 'label_schema_id' | 'assignee' | 'priority' | 'status'>> {
  return request('/tasks', { method: 'POST', body: JSON.stringify(input) })
}

export function updateAnnotationTask(
  taskId: number,
  changes: { assignee?: string; status?: string },
): Promise<{ id: number }> {
  return request(`/tasks/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

export function autoAssignAnnotationTask(
  taskId: number,
): Promise<{ id: number; assignee: string }> {
  return request(`/tasks/${taskId}/auto-assign`, { method: 'POST' })
}

export function skipTaskItem(
  taskId: number,
  itemId: string,
): Promise<{ id: string }> {
  return request(
    `/tasks/${taskId}/items/${encodeURIComponent(itemId)}/skip`,
    { method: 'POST' },
  )
}

export type AIAnnotationSuggestion = {
  label: string
  confidence: number
  reason: string
  model: string
}

export function preannotateDataItem(
  itemId: string,
  taskId: number,
): Promise<AIAnnotationSuggestion> {
  return request(`/data-items/${encodeURIComponent(itemId)}/pre-annotate`, {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId }),
  })
}

export function getPlatformStatistics(
  signal?: AbortSignal,
  projectId?: number,
): Promise<PlatformStatistics> {
  const query = projectId ? `?project_id=${projectId}` : ''
  return request(`/stats${query}`, { signal })
}

export function getReviewItems(
  status: 'pending' | 'approved' | 'returned',
  signal?: AbortSignal,
): Promise<ReviewItem> {
  const query = new URLSearchParams({ status })
  return request(`/reviews?${query}`, { signal })
}

export function reviewDataItem(
  itemId: string,
  decision: 'approved' | 'returned',
  note: string,
): Promise<{ id: string; decision: string; reviewed_by: string; reviewed_at: string; note: string }> {
  return request(`/data-items/${encodeURIComponent(itemId)}/review`, {
    method: 'PUT',
    body: JSON.stringify({ decision, note }),
  })
}

export function getQualityCheck(
  itemId: string,
  signal?: AbortSignal,
): Promise<QualityCheckResult> {
  return request(`/data-items/${encodeURIComponent(itemId)}/quality-check`, {
    signal,
  })
}

export function getPlatformUsers(signal?: AbortSignal): Promise<PlatformUser[]> {
  return request('/users', { signal })
}

export function updatePlatformUserRole(
  userId: number,
  role: string,
): Promise<{ id: number; role: string }> {
  return request(`/users/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  })
}

export function getAuditLogs(signal?: AbortSignal): Promise<{
  items: AuditLog[]
  total: number
  page: number
  page_size: number
}> {
  return request('/audit-logs', { signal })
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
  label: DataLabel | null,
  taskId?: number,
  annotation?: MultimodalAnnotation,
): Promise<{
  id: string
  label: DataLabel | null
  labeled_by: string | null
  labeled_at: string | null
  history_entry: LabelHistoryEntry | null
  annotation: MultimodalAnnotation | null
}> {
  const body: {
    label: DataLabel | null
    task_id?: number
    annotation?: MultimodalAnnotation
  } = { label }
  if (taskId !== undefined) body.task_id = taskId
  if (annotation !== undefined) body.annotation = annotation
  return request(`/data-items/${encodeURIComponent(itemId)}/label`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export type DataItemIssueType = '数据异常' | '标签疑问' | '其他'

export function reportDataItemIssue(
  itemId: string,
  type: DataItemIssueType,
  description: string,
): Promise<{
  type: DataItemIssueType
  description: string
  reported_by: string
  reported_at: string
}> {
  return request(`/data-items/${encodeURIComponent(itemId)}/issues`, {
    method: 'POST',
    body: JSON.stringify({ type, description }),
  })
}
