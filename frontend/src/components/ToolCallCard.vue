<template>
  <div v-if="calls.length || notes.length" class="tools">
    <div v-for="(c, i) in calls" :key="`${c.tool}-${i}`" class="tool">
      <div class="head">
        <span class="title">工具调用 · {{ c.tool }}</span>
        <span class="pill" :class="statusOf(c)">{{ statusLabel(c) }}</span>
        <button
          class="fold"
          type="button"
          :aria-expanded="!isFolded(i)"
          :aria-label="isFolded(i) ? '展开工具调用参果' : '收起工具调用参果'"
          @click="toggle(i)"
        >
          {{ isFolded(i) ? '▸' : '▾' }}
        </button>
      </div>
      <p class="meta">{{ metaText(c) }}</p>
      <p v-if="!isFolded(i)" class="arg">参数 {{ argText(c) }}</p>
      <p v-if="!isFolded(i)" class="res">结果 {{ resultText(c) }}</p>
    </div>
    <div v-if="notes.length" class="notes">
      <span class="note-bar" />
      <p class="note">编排说明 · {{ notes.join('；') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
// 工具调用透明展示卡（职责：按画板形态渲染 done.tool_calls 与编排说明，参果可折叠）
// 链路：SSE done.tool_calls/orchestration.notes → useAgentStream.toMessage → WorkbenchChat → 本组件（只读展示）
// 默认展开（与画板 wtk00 是同态）；状态/文案一律来自后端真返回，前端不编造节点、时效与结论
// 对齐：页面设计 §7 ToolCallCard + FR-5「可展开参果」+ design.pen 画板 -/workbench（wtk00/wtk10/wtk30 状态族）
import { ref } from 'vue';
import type { ToolCall } from '@/types/agent';

defineProps<{ calls: ToolCall[]; notes: string[] }>();

// 折叠态按序号记录：默认全展开，点箭头才收起（画板画的是展开态）
const folded = ref<number[]>([]);
const isFolded = (i: number) => folded.value.includes(i);
const toggle = (i: number) => {
  folded.value = isFolded(i) ? folded.value.filter(v => v !== i) : [...folded.value, i];
};

// 工具出参是各工具自由字典（后端形状不同），前端只做只读取值
type Dict = { [key: string]: unknown };
const dict = (v?: object) => (v ?? {}) as Dict;
const pick = (v: unknown, key: string) =>
  dict(typeof v === 'object' && v !== null ? (v as object) : undefined)[key];
const num = (v: unknown) => (typeof v === 'number' ? v : 0);
const text = (v: unknown) => (typeof v === 'string' ? v : '');

// 状态中文化：ok=已执行；approval_required=结果进审批闸门（账目未动）；其余按业务拒绝
const STATUS_LABEL = { ok: '成功', pending: '待审批', rejected: '被拒' } as const;
const statusOf = (c: ToolCall) =>
  c.approval_required ? 'pending' : c.status === 'ok' ? 'ok' : 'rejected';
const statusLabel = (c: ToolCall) => STATUS_LABEL[statusOf(c)];

const shortTag = (id: string) => (id.length > 10 ? `${id.slice(0, 4)}…${id.slice(-4)}` : id);

const metaText = (c: ToolCall) => {
  const parts: string[] = [];
  if (c.scope) {
    parts.push(`scope ${c.scope}`);
  }
  parts.push(`耗时 ${(num(c.latency_ms) / 1000).toFixed(2)}s`);
  if (typeof c.attempts === 'number') {
    parts.push(`${c.attempts} 次`);
  }
  if (c.trace_id) {
    parts.push(`trace_id ${shortTag(c.trace_id)}`);
  }
  return parts.join(' · ');
};

const argText = (c: ToolCall) => JSON.stringify(dict(c.args));

// 取最高相似度（refs 是 unknown[]，用局部变量累加比 reduce 泛型推断更稳）
const topScore = (refs: unknown[]) => {
  let max = 0;
  refs.forEach(item => {
    const score = num(pick(item, 'score'));
    if (score > max) {
      max = score;
    }
  });
  return max;
};

// 结果一行摘要：只复述后端真返回的字段（后端注入提示词的成句文案在 runtime.summarize，不在此复刻）
const resultText = (c: ToolCall) => {
  if (c.status !== 'ok') {
    return c.message || '工具调用未成功，已回落知识库检索';
  }
  const r = dict(c.result);
  if (c.approval_required) {
    return `已提交审批（账目未变动）· 单号 ${text(r.approval_id) || c.approval_id || '待生成'}`;
  }
  const refs = Array.isArray(r.references) ? r.references : [];
  const lines = {
    'kb.retrieve': `命中 ${num(r.total)} 条 · 相似度 ${topScore(refs).toFixed(2)} · 已注入提示词`,
    'order.query': `订单 ${text(r.outer_id)} 当前为「${text(r.status_label)}」`,
    'logistics.query': `运单 ${text(r.tracking_no)}（${text(r.company)}）状态「${text(r.status_label)}」`,
    'stock.query': `可用库存 ${num(r.available)} 件`,
    'coupon.query': `进行中活动 ${num(r.total)} 个`,
  };
  return lines[c.tool as keyof typeof lines] ?? `已执行 · 返回 ${Object.keys(r).length} 个字段`;
};
</script>

<style scoped>
/* 深底半透明卡（画板 wtk00：12% 白叠底 + 8% 描边，深底上浅字；不套浅气泡，避免白上白糊） */
.tools {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.tool {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  background: var(--reai-glass-border);
  border: 1px solid var(--reai-border);
  border-radius: 8px;
}
.head {
  display: flex;
  gap: 8px;
  align-items: center;
}
.title {
  font-size: var(--reai-fs-caption);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-main);
}
.pill {
  padding: 4px;
  font-size: var(--reai-fs-micro);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-on-light);
  border-radius: 999px;
}
.pill.ok {
  background: var(--reai-online);
}
.pill.pending {
  background: var(--reai-gold);
}
.pill.rejected {
  background: var(--reai-notice);
}
.fold {
  padding: 0;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-soft);
  cursor: pointer;
  background: none;
  border: none;
}
.fold:hover {
  color: var(--reai-text-main);
}
/* 原生 button 不继承 Element Plus 焦点环，显式给键盘焦点 */
.fold:focus-visible {
  outline: 2px solid var(--reai-accent);
  outline-offset: 2px;
}
.meta,
.arg,
.res {
  margin: 0;
  font-size: var(--reai-fs-micro);
  line-height: var(--reai-lh-body);
  overflow-wrap: anywhere;
}
.meta {
  color: var(--reai-text-soft);
}
.arg {
  font-family: var(--reai-font-mono);
  color: var(--reai-text-muted);
}
.res {
  color: var(--reai-text-soft);
}
.notes {
  display: flex;
  gap: 6px;
  align-items: center;
}
.note-bar {
  flex-shrink: 0;
  width: 2px;
  height: 14px;
  background: var(--reai-notice);
  border-radius: 1px;
}
.note {
  margin: 0;
  font-size: var(--reai-fs-micro);
  color: var(--reai-notice);
}
</style>
