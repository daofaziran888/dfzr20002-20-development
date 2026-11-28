<template>
  <section class="dashboard-card package-card">
    <h4>配额对账包</h4>
    <p class="hint">
      把面积占用与功率核验封成同一轮快照，供展位编排复核；保存只读快照，不登记展位、不增加面积占用。
    </p>

    <!-- 保存 / 补存 -->
    <form class="package-form" @submit.prevent="save">
      <label>
        <span>场馆</span>
        <input v-model="venueName" data-testid="pkg-venue" placeholder="如 A馆主展厅" required />
      </label>
      <label>
        <span>面积余量（㎡）</span>
        <input v-model="areaRemaining" data-testid="pkg-area" placeholder="如 28，留空按实时核算" />
      </label>
      <label class="check">
        <input v-model="powerPending" type="checkbox" data-testid="pkg-power-pending" />
        <span>功率仍在核算（先只存面积）</span>
      </label>
      <label>
        <span>经办人</span>
        <input v-model="operator" data-testid="pkg-operator" placeholder="签发员" />
      </label>
      <button class="btn primary" data-testid="pkg-save" type="submit" :disabled="saving">
        {{ saving ? '保存中…' : '保存对账包' }}
      </button>
    </form>

    <p v-if="actionError" class="error-text">{{ actionError }}</p>
    <p v-if="actionMessage" class="action-ok">{{ actionMessage }}</p>

    <!-- 包号回查 -->
    <form class="package-form lookup" @submit.prevent="lookup">
      <label>
        <span>包号回查</span>
        <input v-model="packageNoInput" data-testid="pkg-no-input" placeholder="如 QPKG-20260101-0001" />
      </label>
      <button class="btn" data-testid="pkg-lookup" type="submit">查明细</button>
      <button class="btn ghost" data-testid="pkg-refresh" type="button" @click="refreshLatest">
        刷新最新包号
      </button>
    </form>

    <template v-if="pkg">
      <div class="package-head" :class="pkg.placement_ready ? 'quota-ok' : 'quota-warn'">
        <strong>{{ pkg.package_no }}</strong>
        <span class="badge" :class="pkg.placement_ready ? 'badge-ok' : 'badge-warn'">
          {{ pkg.status }}
        </span>
        <span>{{ pkg.venue_name }} · 第 {{ pkg.rounds?.length ?? 0 }} 轮记录</span>
      </div>

      <p v-if="pkg.warning" class="warn-text" data-testid="pkg-warning">⚠ {{ pkg.warning }}</p>

      <div class="detail-grid">
        <!-- 面积明细 -->
        <article class="detail-block">
          <h5>
            面积占用
            <span v-if="pkg.area_detail_adopted" class="badge badge-ok">已采用</span>
            <span v-else class="badge badge-muted">未封存</span>
          </h5>
          <template v-if="pkg.area_detail">
            <p>
              可用 {{ pkg.area_detail.venue_area }}㎡
              | 已用 {{ pkg.area_detail.total_booth_area }}㎡
              | 剩余 <strong>{{ pkg.area_detail.remaining }}㎡</strong>
            </p>
            <p v-if="pkg.area_detail.correction" class="correction-note">
              场馆更正：{{ pkg.area_detail.corrected_from_remaining }}㎡ →
              {{ pkg.area_detail.remaining }}㎡
              <span v-if="pkg.area_detail.correction_note">（{{ pkg.area_detail.correction_note }}）</span>
            </p>
            <ul class="booth-list">
              <li v-for="b in pkg.area_detail.booths" :key="b.booth_no">
                {{ b.booth_no }}：{{ b.area }}㎡（{{ b.status }}）
              </li>
            </ul>
          </template>
          <p v-else class="empty-state">面积尚未封存</p>
        </article>

        <!-- 功率明细 -->
        <article class="detail-block">
          <h5>
            功率核验
            <span v-if="pkg.power_detail_adopted" class="badge badge-ok">已采用</span>
            <span v-else class="badge badge-muted">未封存</span>
          </h5>
          <template v-if="pkg.power_detail">
            <p>
              设计负荷 {{ pkg.power_detail.total_design_load }}kW
              | 回路总功率 {{ pkg.power_detail.total_circuit_power }}kW
              <span v-if="pkg.power_detail.over_draw > 0" class="text-danger">
                （超载 {{ pkg.power_detail.over_draw }}kW）
              </span>
            </p>
            <ul class="booth-list">
              <li v-for="b in pkg.power_detail.booths" :key="b.booth_no">
                {{ b.booth_no }}：{{ b.total_circuit_power }}kW / 设计 {{ b.design_load }}kW
                <span :class="b.ok ? 'text-success' : 'text-danger'">
                  {{ b.ok ? '通过' : '超限' }}
                </span>
              </li>
            </ul>
          </template>
          <p v-else class="empty-state">功率仍在核算，补齐后才能签发</p>
        </article>
      </div>

      <!-- 采用口径 -->
      <article class="detail-block">
        <h5>签发依据</h5>
        <p v-if="pkg.adopted.round_no">
          采用第 {{ pkg.adopted.round_no }} 轮封存：剩余
          {{ pkg.adopted.area_remaining }}㎡ · 回路总功率
          {{ pkg.adopted.total_circuit_power }}kW
        </p>
        <p v-else class="empty-state">尚无同轮封存结果</p>
        <p v-if="pkg.superseded_areas?.length" class="superseded">
          已被取代：
          <span v-for="s in pkg.superseded_areas" :key="s.round_no">
            第 {{ s.round_no }} 轮 {{ s.remaining }}㎡；
          </span>
        </p>
        <details class="versions">
          <summary>所依据的现场版本（{{ (pkg.source_versions?.version_set || []).join('、') || '—' }}）</summary>
          <ul>
            <li>场馆：{{ pkg.source_versions?.venue?.name }}（{{ pkg.source_versions?.venue?.version }}）</li>
            <li>
              展位：
              <span v-for="b in pkg.source_versions?.booths" :key="b.booth_no">
                {{ b.booth_no }}@{{ b.version }}；
              </span>
            </li>
            <li>
              设计：
              <span v-for="d in pkg.source_versions?.designs" :key="d.booth_no">
                {{ d.booth_no }}@{{ d.version }}；
              </span>
            </li>
            <li>
              用电：
              <span v-for="e in pkg.source_versions?.electrical" :key="e.circuit">
                {{ e.circuit }}@{{ e.version }}；
              </span>
            </li>
          </ul>
        </details>
      </article>

      <!-- 补齐与排位 -->
      <div class="package-actions">
        <button
          v-if="!pkg.placement_ready"
          class="btn"
          data-testid="pkg-complete"
          type="button"
          :disabled="completing"
          @click="complete"
        >
          {{ completing ? '补齐中…' : '补齐功率核验（按实时采集）' }}
        </button>
        <form class="placement-form" @submit.prevent="place">
          <input
            v-model="placementBooth"
            data-testid="pkg-placement-booth"
            placeholder="排位展位编号，如 BOOT-A01"
          />
          <button
            class="btn primary"
            data-testid="pkg-place"
            type="submit"
            :disabled="placing || !pkg.placement_ready"
          >
            {{ placing ? '签发中…' : '凭包办排位' }}
          </button>
        </form>
      </div>
      <p v-if="!pkg.placement_ready" class="hint">
        核对未完成时展示提示，不阻断查询；补齐两项同轮后才能办理新排位。
      </p>

      <!-- 轮次记录 -->
      <details class="versions" open>
        <summary>轮次记录（{{ pkg.rounds?.length ?? 0 }}）</summary>
        <ol class="round-list">
          <li v-for="round in pkg.rounds" :key="round.round_no" :class="round.complete ? 'round-ok' : ''">
            第 {{ round.round_no }} 轮 · {{ formatTime(round.captured_at) }} ·
            面积 {{ round.area ? round.area.remaining + '㎡' : '缺' }} ·
            功率 {{ round.power ? round.power.total_circuit_power + 'kW' : '缺' }}
            <span v-if="round.area_correction" class="correction-note">
              （更正 {{ round.area_correction.from_remaining }}→{{ round.area_correction.to_remaining }}㎡）
            </span>
            <span v-if="round.complete" class="text-success"> · 同轮封存</span>
          </li>
        </ol>
      </details>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  saveQuotaPackage,
  fetchQuotaPackage,
  fetchLatestQuotaPackage,
  completeQuotaPackage,
  issueQuotaPlacement,
} from '@/api/exhibition-client'
import type { QuotaPackage, PlacementResult } from '@/data/exhibition-types'

const venueName = ref('A馆主展厅')
const areaRemaining = ref('28')
const powerPending = ref(true)
const operator = ref('签发员')
const packageNoInput = ref('')
const pkg = ref<QuotaPackage | null>(null)

const saving = ref(false)
const completing = ref(false)
const placing = ref(false)
const actionError = ref('')
const actionMessage = ref('')

const placementBooth = ref('BOOT-A01')
// 保存请求的稳定幂等号：响应中断后再次点击仍用它，后端据此取回原包而不是新开一轮。
const pendingSaveId = ref('')

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

async function save() {
  actionError.value = ''
  actionMessage.value = ''
  saving.value = true
  // 首次保存生成幂等号；若上次响应中断，本次沿用同一个号重试。
  const clientRequestId = pendingSaveId.value || requestId('save')
  pendingSaveId.value = clientRequestId
  const area = areaRemaining.value.trim()
    ? { remaining: Number(areaRemaining.value.trim()), note: '现场余量' }
    : null
  const power = powerPending.value ? null : { booths: [] }
  const body = {
    venue_name: venueName.value.trim(),
    area,
    power,
    operator: operator.value.trim(),
    client_request_id: clientRequestId,
    capture_power_live: !powerPending.value,
  }
  try {
    const result = await saveQuotaPackage(body)
    if (!result.ok || !result.package) throw new Error(result.reason || '保存失败')
    pendingSaveId.value = ''
    pkg.value = result.package
    packageNoInput.value = result.package.package_no
    actionMessage.value = result.reused
      ? `已取回原对账包 ${result.package.package_no}（未重复建包）`
      : `已保存对账包 ${result.package.package_no}（第 ${result.round_no} 轮）`
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '保存对账包失败'
  } finally {
    saving.value = false
  }
}

async function lookup() {
  actionError.value = ''
  actionMessage.value = ''
  const no = packageNoInput.value.trim()
  if (!no) {
    actionError.value = '请先输入包号'
    return
  }
  try {
    pkg.value = await fetchQuotaPackage(no)
    actionMessage.value = `已回查对账包 ${no}`
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '回查失败'
  }
}

async function refreshLatest() {
  actionError.value = ''
  actionMessage.value = ''
  try {
    const latest = await fetchLatestQuotaPackage(venueName.value.trim())
    pkg.value = latest
    packageNoInput.value = latest.package_no
    actionMessage.value = `已刷新到最新包号 ${latest.package_no}`
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '刷新包号失败'
  }
}

async function complete() {
  if (!pkg.value) return
  actionError.value = ''
  actionMessage.value = ''
  completing.value = true
  try {
    const result = await completeQuotaPackage(pkg.value.package_no, {
      operator: operator.value.trim(),
      client_request_id: requestId('complete'),
    })
    if (!result.ok || !result.package) throw new Error(result.reason || '补齐失败')
    pkg.value = result.package
    actionMessage.value = `已补齐并同轮封存，采用第 ${result.package.adopted_round} 轮面积 ${result.package.adopted.area_remaining}㎡`
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '补齐功率核验失败'
  } finally {
    completing.value = false
  }
}

async function place() {
  if (!pkg.value) return
  actionError.value = ''
  actionMessage.value = ''
  placing.value = true
  try {
    const result: PlacementResult = await issueQuotaPlacement(pkg.value.package_no, {
      booth_no: placementBooth.value.trim(),
      operator: operator.value.trim(),
      client_request_id: requestId('place'),
    })
    if (!result.ok) {
      throw new Error(result.reason || '排位签发失败')
    }
    const placement = result.placement as Record<string, unknown> | undefined
    actionMessage.value = `${result.reason}；采用面积余量 ${placement?.adopted_area_remaining ?? '—'}㎡`
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : '排位签发失败'
  } finally {
    placing.value = false
  }
}
</script>

<style scoped>
.package-card { background: #fff; border: 1px solid var(--border); }
.hint { font-size: 12px; color: var(--muted); margin: 4px 0 10px; }
.package-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; margin-bottom: 10px; }
.package-form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.package-form label.check { flex-direction: row; align-items: center; gap: 6px; }
.package-form input { border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.package-form.lookup { padding-top: 8px; border-top: 1px dashed var(--border); }
.package-head { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 10px; border-radius: 6px; font-size: 13px; margin-bottom: 8px; }
.badge { font-size: 11px; padding: 1px 8px; border-radius: 10px; }
.badge-ok { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }
.badge-warn { background: #fff7e6; color: #d46b08; border: 1px solid #ffd591; }
.badge-muted { background: #f0f2f5; color: #888; border: 1px solid #e0e3e8; }
.warn-text { color: #d46b08; font-size: 13px; }
.action-ok { color: #389e0d; font-size: 13px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.detail-block { background: #f8f9fa; border-radius: 8px; padding: 12px; margin-bottom: 10px; font-size: 13px; }
.detail-block h5 { margin: 0 0 8px; display: flex; gap: 8px; align-items: center; }
.booth-list { margin: 6px 0 0; padding-left: 18px; color: #475569; }
.correction-note { color: #d46b08; }
.superseded { color: var(--muted); font-size: 12px; }
.versions { margin-top: 8px; font-size: 12px; color: var(--muted); }
.versions ul { margin: 6px 0 0; padding-left: 18px; }
.package-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 10px 0; }
.placement-form { display: flex; gap: 8px; }
.placement-form input { border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.round-list { margin: 6px 0 0; padding-left: 18px; color: #475569; }
.round-ok { color: #389e0d; }
.text-success { color: #52c41a; }
.text-danger { color: #f5222d; }
@media (max-width: 900px) { .detail-grid { grid-template-columns: 1fr; } }
</style>
