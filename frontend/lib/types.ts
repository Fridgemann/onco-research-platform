export interface User {
  id: string
  email: string
  full_name: string
  role: string
  is_active: boolean
  is_verified: boolean
  created_at: string
  last_login: string | null
}

export interface Workspace {
  id: string
  name: string
  description: string | null
  owner_id: string
  created_at: string
}

export interface WorkspaceMember {
  id: string
  user_id: string
  email: string
  role: 'owner' | 'collaborator'
  invited_by: string
  joined_at: string
}

export interface WorkspaceInvite {
  id: string
  workspace_id: string
  invited_email: string
  status: 'pending' | 'accepted' | 'revoked'
  invited_by: string
  created_at: string
  expires_at: string
  accepted_at: string | null
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
