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
  is_active?: boolean
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
  next_cursor: string | null
  pit_id: string | null
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
  latest_version: number | null
}

export type DatasetVersion = {
  id: number
  version: number
  imported_count: number
  status: string
  source_name: string
  created_by: string
  created_at: string
}

export type ExportHistoryRecord = {
  id: number
  dataset_id: number | null
  label_status: string
  export_format: 'csv' | 'jsonl'
  status: string
  item_count: number
  created_at: string
  completed_at: string | null
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
  dataset_version: number | null
  assignee: string
  second_assignee: string | null
  priority: '高' | '中' | '低'
  status: string
  deadline: string | null
  instructions: string
  created_by: string
  created_at: string
  total_items: number
  labeled_items: number
}

export type AnnotationTasksPage = {
  items: AnnotationTask[]
  total: number
  page: number
  page_size: number
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
  page: number
  page_size: number
}

export type DatasetImportPreview = {
  dataset_id: number
  record_count: number
  fields: string[]
  preview: Array<Record<string, unknown>>
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

export type AppNotification = {
  id: number
  title: string
  body: string
  link: string
  is_read: boolean
  created_at: string
}

export type QualityRule = {
  key: 'empty_content' | 'min_length' | 'missing_label' | 'missing_annotator' | 'duplicate_content'
  name: string
  enabled: boolean
  threshold: number | null
}

export type AIEvaluationSummary = {
  evaluated_count: number
  accepted_count: number
  acceptance_rate: number
  by_model: Array<{
    model: string
    evaluated_count: number
    accepted_count: number
  }>
}

export type QualityTrend = {
  month: string
  approved: number
  returned: number
  total: number
}

export type AnnotationArbitrationItem = {
  task_id: number
  item_id: string
  task_name: string
  candidates: Array<{ annotator: string; label: string }>
}

export type AnnotationIssue = {
  id: number
  item_id: string
  dataset_id: number
  project_id: number
  issue_type: DataItemIssueType
  description: string
  reported_by: string
  status: '待处理' | '处理中' | '已解决' | '已关闭'
  assignee: string | null
  resolution: string
  created_at: string
  updated_at: string
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

export function changeCurrentPassword(
  currentPassword: string,
  newPassword: string,
): Promise<null> {
  return request('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })
}

export function getRecoveryEmail(): Promise<{ email: string | null; verified: boolean }> {
  return request('/auth/recovery-email')
}

export function sendRecoveryEmailCode(email: string): Promise<null> {
  return request('/auth/recovery-email/send-code', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function verifyRecoveryEmail(email: string, code: string): Promise<null> {
  return request('/auth/recovery-email/verify', {
    method: 'POST',
    body: JSON.stringify({ email, code }),
  })
}

export function sendForgotPasswordCode(username: string): Promise<null> {
  return request('/auth/forgot-password/send-code', {
    method: 'POST',
    body: JSON.stringify({ username }),
  })
}

export function resetForgottenPassword(
  username: string,
  code: string,
  newPassword: string,
): Promise<null> {
  return request('/auth/forgot-password/reset', {
    method: 'POST',
    body: JSON.stringify({ username, code, new_password: newPassword }),
  })
}

export function getCurrentUser(signal?: AbortSignal): Promise<User> {
  return request<User>('/auth/me', { signal })
}

export function updateOnlinePresence(): Promise<{
  online_users: number
  window_minutes: number
}> {
  return request('/auth/presence', { method: 'POST' })
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
  after?: string,
  pitId?: string,
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
  if (after) query.set('after', after)
  if (pitId) query.set('pit_id', pitId)
  return request<DataItemsPage>(`/data-items?${query}`, { signal })
}

export function getDatasets(signal?: AbortSignal): Promise<DatasetRecord[]> {
  return request('/datasets', { signal })
}

export function getDatasetVersions(
  datasetId: number,
  signal?: AbortSignal,
): Promise<DatasetVersion[]> {
  return request(`/datasets/${datasetId}/versions`, { signal })
}

export function getExportHistory(
  signal?: AbortSignal,
): Promise<{ items: ExportHistoryRecord[]; total: number; page: number; page_size: number }> {
  return request('/exports/history?page_size=20', { signal })
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
): Promise<{ dataset_id: number; imported_count: number; dataset_version: number | null }> {
  const body = new FormData()
  body.set('file', file)
  return request(`/datasets/${datasetId}/import`, { method: 'POST', body })
}

export function previewDatasetFile(
  datasetId: number,
  file: File,
): Promise<DatasetImportPreview> {
  const body = new FormData()
  body.set('file', file)
  body.set('preview_only', 'true')
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

export function getAnnotationTasks(signal?: AbortSignal): Promise<AnnotationTask[]>
export function getAnnotationTasks(
  signal?: AbortSignal,
  page?: number,
  pageSize?: number,
): Promise<AnnotationTasksPage>
export function getAnnotationTasks(
  signal?: AbortSignal,
  page?: number,
  pageSize?: number,
): Promise<AnnotationTask[] | AnnotationTasksPage> {
  const query = new URLSearchParams()
  if (page !== undefined) query.set('page', String(page))
  if (pageSize !== undefined) query.set('page_size', String(pageSize))
  const suffix = query.size ? `?${query}` : ''
  return request(`/tasks${suffix}`, { signal })
}

export function createAnnotationTask(input: {
  name: string
  dataset_id: number
  label_schema_id: number
  assignee: string
  second_assignee?: string | null
  priority: AnnotationTask['priority']
  deadline: string
  instructions: string
}): Promise<Pick<AnnotationTask, 'id' | 'name' | 'dataset_id' | 'label_schema_id' | 'assignee' | 'second_assignee' | 'priority' | 'status'>> {
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

export function batchAssignAnnotationTasks(
  taskIds: number[],
  assignee: string,
): Promise<{ task_ids: number[]; assignee: string }> {
  return request('/tasks/batch-assign', {
    method: 'POST',
    body: JSON.stringify({ task_ids: taskIds, assignee }),
  })
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
  options: {
    page?: number
    pageSize?: number
    datasetId?: number
    annotator?: string
    dateFrom?: string
    dateTo?: string
  } = {},
  signal?: AbortSignal,
): Promise<ReviewItem> {
  const query = new URLSearchParams({
    status,
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 20),
  })
  if (options.datasetId !== undefined) query.set('dataset_id', String(options.datasetId))
  if (options.annotator) query.set('annotator', options.annotator)
  if (options.dateFrom) query.set('date_from', options.dateFrom)
  if (options.dateTo) query.set('date_to', options.dateTo)
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

export function createPlatformUser(input: {
  username: string
  password: string
  role: string
}): Promise<PlatformUser> {
  return request('/users', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updatePlatformUser(
  userId: number,
  changes: {
    username?: string
    role?: string
    password?: string
    is_active?: boolean
  },
): Promise<PlatformUser> {
  return request(`/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
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
  status?: string
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

export function getQualityRules(signal?: AbortSignal): Promise<QualityRule[]> {
  return request('/quality-rules', { signal })
}

export function saveQualityRules(rules: QualityRule[]): Promise<QualityRule[]> {
  return request('/quality-rules', {
    method: 'PUT',
    body: JSON.stringify({ rules }),
  })
}

export function getAIEvaluation(signal?: AbortSignal): Promise<AIEvaluationSummary> {
  return request('/ai-evaluation', { signal })
}

export function getQualityTrends(
  datasetId?: number,
  signal?: AbortSignal,
): Promise<QualityTrend[]> {
  const query = datasetId === undefined ? '' : `?dataset_id=${datasetId}`
  return request(`/quality-trends${query}`, { signal })
}

export function getAnnotationArbitrations(
  signal?: AbortSignal,
): Promise<{
  items: AnnotationArbitrationItem[]
  total: number
  page: number
  page_size: number
}> {
  return request('/arbitrations?page_size=100', { signal })
}

export function resolveAnnotationArbitration(
  taskId: number,
  itemId: string,
  label: string,
  note: string,
): Promise<{ task_id: number; item_id: string; label: string }> {
  return request(`/tasks/${taskId}/items/${encodeURIComponent(itemId)}/arbitrate`, {
    method: 'POST',
    body: JSON.stringify({ label, note }),
  })
}

export function getAnnotationIssues(
  options: { page?: number; pageSize?: number; status?: AnnotationIssue['status'] } = {},
  signal?: AbortSignal,
): Promise<{ items: AnnotationIssue[]; total: number; page: number; page_size: number }> {
  const query = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 20),
  })
  if (options.status) query.set('status', options.status)
  return request(`/issues?${query}`, { signal })
}

export function updateAnnotationIssue(
  issueId: number,
  changes: {
    status?: AnnotationIssue['status']
    assignee?: string | null
    resolution?: string
  },
): Promise<{ id: number }> {
  return request(`/issues/${issueId}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

export function getNotifications(
  signal?: AbortSignal,
): Promise<{ items: AppNotification[]; total: number; page: number; page_size: number }> {
  return request('/notifications?page_size=10', { signal })
}

export function markNotificationRead(notificationId: number): Promise<{ id: number }> {
  return request(`/notifications/${notificationId}/read`, { method: 'PATCH' })
}
