export interface User {
  id: string
  role: string
  is_active: boolean
  created_at: string
}

export interface Workspace {
  id: string
  name: string
  description: string | null
  created_by: string
  created_at: string
}

export interface Dataset {
  id: string
  workspace_id: string
  filename: string
  content_type: string
  file_size: number
  description: string | null
  uploaded_by: string
  created_at: string
}

export interface AnalysisJob {
  id: string
  dataset_id: string
  workspace_id: string
  requested_by: string
  job_type: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  parameters: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}
