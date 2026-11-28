/** 跨模块会展引擎 API：执行历史、配额视图、进度推进等。 */
import { request } from './client'
import type {
  ExhibitionHistory,
  QuotaSummary,
  DAGStatus,
  HandoverResult,
  QuotaPackage,
  SavePackageResult,
  PackageReadiness,
  PlacementResult,
} from '@/data/exhibition-types'

const EXHIBITION_BASE = '/api/exhibition'

export async function fetchBoothHistory(boothNo: string): Promise<ExhibitionHistory> {
  const response = await request(`${EXHIBITION_BASE}/${boothNo}/history`)
  if (!response.ok) throw new Error('执行历史查询失败')
  return await response.json()
}

export async function advanceConstructionNode(nodeId: number): Promise<{ ok: boolean; reason: string }> {
  const response = await request(`${EXHIBITION_BASE}/advance/${nodeId}`, { method: 'POST' })
  return await response.json()
}

export async function fetchQuotaSummary(): Promise<QuotaSummary> {
  const response = await request(`${EXHIBITION_BASE}/quota`)
  if (!response.ok) throw new Error('配额数据读取失败')
  return await response.json()
}

export async function signoffChecklist(checklistId: number): Promise<{ ok: boolean; reason: string }> {
  const response = await request(`${EXHIBITION_BASE}/checklist/${checklistId}/signoff`, { method: 'POST' })
  return await response.json()
}

export async function confirmHandover(handoverId: number): Promise<HandoverResult> {
  const response = await request(`${EXHIBITION_BASE}/handover/${handoverId}/confirm`, { method: 'POST' })
  return await response.json()
}

export async function issueChangeOrder(changeId: number): Promise<{ ok: boolean; reason: string }> {
  const response = await request(`${EXHIBITION_BASE}/change/${changeId}/issue`, { method: 'POST' })
  return await response.json()
}

export async function fetchSafetyStatus(boothNo: string): Promise<{ ok: boolean; reason: string }> {
  const response = await request(`${EXHIBITION_BASE}/safety/${boothNo}`)
  return await response.json()
}

export async function fetchDAGStatus(): Promise<DAGStatus> {
  const response = await request(`${EXHIBITION_BASE}/dag/validate`)
  return await response.json()
}

export async function fetchScheduleConflicts(): Promise<{ conflicts: Record<string, unknown>[]; count: number }> {
  const response = await request(`${EXHIBITION_BASE}/conflicts`)
  return await response.json()
}

// ---------- 配额对账包 ----------

/** 后端拒绝时返回 { detail }；统一成 { ok:false, reason }，页面可直接展示。 */
async function readPackageResult<T extends { ok: boolean; reason?: string }>(
  response: Response,
): Promise<T> {
  const payload = (await response.json()) as T & { detail?: string }
  if (typeof payload.detail === 'string') {
    return { ...payload, ok: false, reason: payload.detail }
  }
  return payload
}

export async function saveQuotaPackage(body: {
  venue_name: string
  area?: Record<string, unknown> | null
  power?: Record<string, unknown> | null
  operator?: string
  client_request_id?: string
  package_no?: string
  capture_power_live?: boolean
}): Promise<SavePackageResult> {
  const response = await request(`${EXHIBITION_BASE}/quota/packages`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return await readPackageResult<SavePackageResult>(response)
}

export async function fetchQuotaPackage(packageNo: string): Promise<QuotaPackage> {
  const response = await request(`${EXHIBITION_BASE}/quota/packages/${encodeURIComponent(packageNo)}`)
  if (!response.ok) throw new Error(`对账包 ${packageNo} 查询失败`)
  return await response.json()
}

export async function fetchLatestQuotaPackage(venueName: string): Promise<QuotaPackage> {
  const query = new URLSearchParams({ venue_name: venueName }).toString()
  const response = await request(`${EXHIBITION_BASE}/quota/packages/latest?${query}`)
  if (!response.ok) throw new Error(`场馆 ${venueName} 暂无对账包`)
  return await response.json()
}

export async function fetchPackageReadiness(packageNo: string): Promise<PackageReadiness> {
  const response = await request(`${EXHIBITION_BASE}/quota/packages/${encodeURIComponent(packageNo)}/readiness`)
  if (!response.ok) throw new Error('核对状态读取失败')
  return await response.json()
}

export async function completeQuotaPackage(
  packageNo: string,
  body: {
    power?: Record<string, unknown> | null
    area?: Record<string, unknown> | null
    operator?: string
    client_request_id?: string
  },
): Promise<SavePackageResult> {
  const response = await request(`${EXHIBITION_BASE}/quota/packages/${encodeURIComponent(packageNo)}/complete`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return await readPackageResult<SavePackageResult>(response)
}

export async function issueQuotaPlacement(
  packageNo: string,
  body: { booth_no: string; slot_no?: string; operator?: string; client_request_id?: string },
): Promise<PlacementResult> {
  const response = await request(`${EXHIBITION_BASE}/quota/packages/${encodeURIComponent(packageNo)}/placements`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return await readPackageResult<PlacementResult>(response)
}