<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>配额与冲突看板</h2>
        <p class="page-desc">实时查看面积配额、功率超载、排期冲突和 DAG 拓扑状态</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="refresh-quota" type="button" @click="refresh">
          刷新看板
        </button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <!-- 综合状态 -->
    <div class="overall-status" :class="summary?.overall_ok ? 'status-ok' : 'status-warn'">
      <span class="status-dot"></span>
      {{ summary?.overall_ok ? '全场正常' : '存在异常项' }}
    </div>

    <!-- DAG 状态 -->
    <section class="dashboard-card">
      <h4>DAG 拓扑状态</h4>
      <div v-if="dagStatus">
        <p>
          <span :class="dagStatus.has_cycle ? 'text-danger' : 'text-success'">
            {{ dagStatus.has_cycle ? '检测到环：' + (dagStatus.cycle || []).join(' → ') : '拓扑无环' }}
          </span>
          | 共 {{ dagStatus.node_count }} 个节点
        </p>
        <div v-if="dagStatus.topological_order?.length" class="dag-order">
          <span class="dag-label">拓扑顺序：</span>
          <span v-for="(name, idx) in dagStatus.topological_order" :key="name" class="dag-node">
            {{ idx + 1 }}. {{ name }}
          </span>
        </div>
      </div>
      <p v-else class="empty-state">加载中...</p>
    </section>

    <!-- 面积配额 -->
    <section class="dashboard-card">
      <h4>面积配额</h4>
      <div v-if="summary?.area_quotas?.length">
        <article
          v-for="item in summary.area_quotas"
          :key="item.venue_id"
          class="quota-item"
          :class="item.ok ? 'quota-ok' : 'quota-warn'"
        >
          <strong>{{ item.venue }}</strong>
          <span v-if="(item.quota as Record<string, number>).venue_area">
            可用 {{ (item.quota as Record<string, number>).venue_area }}㎡
            | 已用 {{ (item.quota as Record<string, number>).total_booth_area }}㎡
            | 剩余 {{ (item.quota as Record<string, number>).remaining }}㎡
          </span>
          <span v-if="!item.ok" class="text-danger">⚠ {{ item.reason }}</span>
        </article>
      </div>
      <p v-else class="empty-state">暂无面积配额数据</p>
    </section>

    <!-- 功率配额 -->
    <section class="dashboard-card">
      <h4>功率配额</h4>
      <div v-if="summary?.power_quotas?.length">
        <article
          v-for="item in summary.power_quotas"
          :key="item.quota.booth_no"
          class="quota-item"
          :class="item.ok ? 'quota-ok' : 'quota-warn'"
        >
          <strong>展位 {{ item.quota.booth_no }}</strong>
          <span>
            设计负荷 {{ item.quota.design_load }}kW
            | 回路总功率 {{ item.quota.total_circuit_power }}kW
          </span>
          <span v-if="!item.ok" class="text-danger">⚠ {{ item.reason }}</span>
        </article>
      </div>
      <p v-else class="empty-state">暂无功率配额数据</p>
    </section>

    <!-- 配额对账包 -->
    <QuotaPackagePanel />

    <!-- 排期冲突 -->
    <section class="dashboard-card">
      <h4>排期冲突（{{ summary?.schedule_conflict_count ?? 0 }}）</h4>
      <div v-if="summary?.schedule_conflicts?.length">
        <article
          v-for="(conflict, idx) in summary.schedule_conflicts"
          :key="idx"
          class="quota-item quota-warn"
        >
          <strong>{{ conflict.exhibit }}</strong>
          <span>{{ conflict.conflict }}</span>
        </article>
      </div>
      <p v-else class="empty-state">暂无排期冲突</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { fetchQuotaSummary, fetchDAGStatus } from '@/api/exhibition-client'
import type { QuotaSummary, DAGStatus } from '@/data/exhibition-types'
import QuotaPackagePanel from '@/views/QuotaPackagePanel.vue'

const summary = ref<QuotaSummary | null>(null)
const dagStatus = ref<DAGStatus | null>(null)
const errorMessage = ref('')

async function refresh() {
  errorMessage.value = ''
  try {
    const [quota, dag] = await Promise.all([
      fetchQuotaSummary(),
      fetchDAGStatus(),
    ])
    summary.value = quota
    dagStatus.value = dag
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '看板数据加载失败'
  }
}

onMounted(refresh)
</script>

<style scoped>
.overall-status {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; border-radius: 8px; margin-bottom: 16px;
  font-size: 16px; font-weight: 600;
}
.status-ok { background: #f6ffed; color: #52c41a; }
.status-warn { background: #fff7e6; color: #fa8c16; }
.status-dot {
  width: 10px; height: 10px; border-radius: 50%;
  display: inline-block;
}
.status-ok .status-dot { background: #52c41a; }
.status-warn .status-dot { background: #fa8c16; }
.dashboard-card {
  background: #f8f9fa; border-radius: 8px;
  padding: 16px; margin-bottom: 16px;
}
.dashboard-card h4 { margin: 0 0 12px; color: #333; }
.quota-item {
  display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
  padding: 10px; border-radius: 6px; margin-bottom: 8px;
  font-size: 13px;
}
.quota-ok { background: #f6ffed; }
.quota-warn { background: #fff7e6; }
.dag-order { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; }
.dag-label { font-size: 12px; color: #999; }
.dag-node {
  font-size: 12px; padding: 2px 8px; background: #e8f4ff;
  border-radius: 4px; color: #1890ff;
}
.text-success { color: #52c41a; }
.text-danger { color: #f5222d; }
</style>