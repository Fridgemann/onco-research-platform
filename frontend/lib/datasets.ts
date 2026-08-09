import { apiFetch } from './api'
import type { DatasetInspect } from './types'

/**
 * Inspect a dataset: sample rows, per-column missingness, and a display-type
 * hint. Figures describe `profile.profiled_rows` — when the profile is
 * partial the true row count is unknown and reported as null.
 *
 * Pass a signal to abandon the request when the selection moves on: a slow
 * response for a previously selected dataset must never be displayed.
 */
export async function fetchDatasetInspect(
  workspaceId: string,
  datasetId: string,
  signal?: AbortSignal,
): Promise<DatasetInspect> {
  return apiFetch<DatasetInspect>(
    `/api/workspaces/${workspaceId}/datasets/${datasetId}/inspect`,
    { signal },
  )
}

/** Upload limits, mirrored from the backend so they can be shown up front.
 *  The backend enforces the same rules — this is convenience, not authority. */
export const UPLOAD_MAX_BYTES = 50 * 1024 * 1024
export const UPLOAD_ACCEPT = '.csv'
export const UPLOAD_MAX_LABEL = '50 MB'

/** Catch an unusable file before uploading it. Deliberately avoids echoing a
 *  rounded size, so a file one byte over the cap cannot be reported as
 *  "50.0 MB, maximum 50 MB". */
export function checkUploadFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return 'Only CSV files can be analysed. Export your data as CSV and try again.'
  }
  if (file.size === 0) {
    return 'This file is empty.'
  }
  if (file.size > UPLOAD_MAX_BYTES) {
    return `This file exceeds the ${UPLOAD_MAX_LABEL} limit.`
  }
  return null
}
