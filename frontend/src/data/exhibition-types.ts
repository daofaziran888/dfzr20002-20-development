/** 会展引擎专用类型 */

export interface EventRecord {
  id: number
  timestamp: number
  module: string
  entry_id: number
  action: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  extra: Record<string, unknown>
}

export interface SafetyStatus {
  ok: boolean
  reason: string
  total_inspections: number
  failed_inspections: Record<string, unknown>[]
}

export interface ElectricalQuota {
  booth_no: string
  design_load: number
  total_circuit_power: number
  over_draw: number
  circuits: Record<string, unknown>[]
}

export interface ExhibitionHistory {
  booth_no: string
  booth: Record<string, unknown> | null
  design: Record<string, unknown> | null
  events: EventRecord[]
  event_count: number
  current_safety: SafetyStatus
  current_electrical: { ok: boolean; reason: string; quota: ElectricalQuota }
  schedule_conflicts: Record<string, unknown>[]
}

export interface QuotaItem {
  venue: string
  venue_id: number
  ok: boolean
  reason: string
  quota: Record<string, unknown>
}

export interface PowerQuotaItem {
  ok: boolean
  reason: string
  quota: ElectricalQuota
}

export interface ScheduleConflict {
  transport_id: number
  exhibit: string
  arrival: string
  schedule_id: number
  event: string
  setup_start: string
  conflict: string
}

export interface QuotaSummary {
  area_quotas: QuotaItem[]
  power_quotas: PowerQuotaItem[]
  schedule_conflicts: ScheduleConflict[]
  schedule_conflict_count: number
  dag_cycle: string[] | null
  dag_ok: boolean
  overall_ok: boolean
}

export interface DAGStatus {
  cycle: string[] | null
  has_cycle: boolean
  topological_order: string[]
  node_count: number
}

export interface HandoverResult {
  ok: boolean
  reason: string
  handover?: Record<string, unknown>
  validation?: Record<string, unknown>
}

// ---------- 配额对账包 ----------

export interface AreaDetail {
  ok: boolean
  venue_name: string
  venue_area: number
  total_booth_area: number
  remaining: number
  booths: { booth_no: string; area: number; status: string }[]
  reason: string
  correction?: boolean
  corrected_from_remaining?: number
  correction_note?: string
}

export interface PowerBoothDetail {
  booth_no: string
  ok: boolean
  design_load: number
  total_circuit_power: number
  over_draw: number
  circuits: { circuit_id: string; power: number; status?: string }[]
  reason: string
}

export interface PowerDetail {
  ok: boolean
  booths: PowerBoothDetail[]
  total_design_load: number
  total_circuit_power: number
  over_draw: number
  reason: string
}

export interface SourceVersions {
  venue: { name: string; id: number | null; version: string }
  booths: { booth_no: string; version: string }[]
  designs: { booth_no: string; version: string }[]
  electrical: { circuit: string; booth_no: string; version: string }[]
  version_set: string[]
}

export interface PackageRound {
  round_no: number
  captured_at: number
  area: AreaDetail | null
  power: PowerDetail | null
  source_versions: SourceVersions
  operator: string
  reason: string
  complete: boolean
  missing: string[]
  area_source_round?: number
  area_correction?: { from_remaining: number; to_remaining: number; note: string }
}

export interface SupersededArea {
  round_no: number
  remaining: number
  venue_area: number
  total_booth_area: number
  reason: string
}

export interface QuotaPackage {
  id: number
  package_no: string
  venue_name: string
  status: string
  missing: string[]
  warning: string
  rounds: PackageRound[]
  created_at: number
  updated_at?: number
  area_round?: number
  power_round?: number
  adopted_round?: number
  adopted_at?: number
  area_detail: AreaDetail | null
  power_detail: PowerDetail | null
  area_detail_adopted: boolean
  power_detail_adopted: boolean
  placement_ready: boolean
  adopted: {
    round_no: number | null
    area_remaining: number | null
    area_venue_area: number | null
    total_circuit_power: number | null
    sealed_at: number | null
  }
  superseded_areas: SupersededArea[]
  source_versions: SourceVersions
  self_area_occupancy: number
  self_area_note: string
}

export interface SavePackageResult {
  ok: boolean
  created?: boolean
  reused?: boolean
  package_no?: string
  round_no?: number
  missing?: string[]
  warning?: string
  package?: QuotaPackage
  reason?: string
}

export interface PackageReadiness {
  ok: boolean
  package_no: string
  ready: boolean
  status: string
  missing: string[]
  warning: string
  message: string
  package: QuotaPackage
}

export interface PlacementResult {
  ok: boolean
  reason: string
  package_no?: string
  reused?: boolean
  missing?: string[]
  placement?: Record<string, unknown>
  basis?: Record<string, unknown>
}