<script setup lang="ts">
import { computed } from 'vue'
import type { AgentEvent, RunStatus } from '../types'

const props = defineProps<{
  events: AgentEvent[]
  runStatus: RunStatus
}>()

const agents = [
  { id: 'brief', label: '需求增强', icon: 'spark' },
  { id: 'manager', label: '团队经理', icon: 'grid' },
  { id: 'discovery', label: '需求洞察', icon: 'spark' },
  { id: 'product', label: '产品策划', icon: 'grid' },
  { id: 'experience', label: '体验设计', icon: 'pen' },
  { id: 'contract', label: '交互契约', icon: 'grid' },
  { id: 'builder', label: 'Demo 构建', icon: 'code' },
  { id: 'runner', label: '产物验证', icon: 'code' },
  { id: 'reviewer', legacyIds: ['qa'], label: '独立评审', icon: 'check' },
]

const rows = computed(() =>
  agents.map((agent) => {
    const legacyIds = 'legacyIds' in agent ? (agent.legacyIds ?? []) : []
    const eventIds = [agent.id, ...legacyIds]
    const events = props.events.filter((event) => eventIds.includes(event.agent_id))
    const last = events.at(-1)
    return {
      ...agent,
      status: last?.status ?? 'waiting',
      message: last?.message ?? '等待上游 Agent',
      iteration: last?.iteration ?? 0,
    }
  }),
)
</script>

<template>
  <div class="agent-timeline" :class="`is-${runStatus}`">
    <div v-for="agent in rows" :key="agent.id" class="agent-row" :class="`agent-${agent.status}`">
      <div class="agent-avatar" aria-hidden="true">
        <svg v-if="agent.icon === 'spark'" viewBox="0 0 24 24"><path d="m12 3 1.4 4.6L18 9l-4.6 1.4L12 15l-1.4-4.6L6 9l4.6-1.4L12 3Z"/><path d="m18.5 15 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z"/></svg>
        <svg v-else-if="agent.icon === 'grid'" viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="2"/><rect x="14" y="4" width="6" height="6" rx="2"/><rect x="4" y="14" width="6" height="6" rx="2"/><rect x="14" y="14" width="6" height="6" rx="2"/></svg>
        <svg v-else-if="agent.icon === 'pen'" viewBox="0 0 24 24"><path d="m5 19 1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L9 18l-4 1Z"/><path d="m14.5 6.5 3 3"/></svg>
        <svg v-else-if="agent.icon === 'code'" viewBox="0 0 24 24"><path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5M14 4l-4 16"/></svg>
        <svg v-else viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>
      </div>
      <div class="agent-copy">
        <div class="agent-title"><strong>{{ agent.label }}</strong><span>{{ agent.iteration ? `返工 ${agent.iteration}` : agent.status === 'completed' ? '完成' : agent.status === 'running' ? '工作中' : agent.status === 'failed' ? '中断' : '待命' }}</span></div>
        <p>{{ agent.message }}</p>
      </div>
      <span v-if="agent.status === 'running'" class="agent-spinner" aria-label="正在处理"></span>
      <svg v-else-if="agent.status === 'completed'" class="agent-check" viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-9"/></svg>
    </div>
  </div>
</template>
