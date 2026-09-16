<template>
  <section class="queue">
    <div class="head">
      <span class="title">会话队列</span>
      <el-tag v-if="demo" size="small" type="warning" effect="plain">演示数据</el-tag>
      <span class="count">{{ loading ? '加载中…' : `${total} 条` }}</span>
    </div>

    <div class="chips">
      <button
        v-for="tab in QUEUE_TABS"
        :key="tab.key"
        class="chip"
        :class="{ 'chip-on': tab.key === status }"
        type="button"
        @click="emit('filter', tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 技能组过滤（FR-7 技能组）：组清单由后端 /workbench/load 带出，空=全部 -->
    <div v-if="(skillGroups || []).length" class="chips skill-chips">
      <button
        class="chip"
        :class="{ 'chip-on': skill === '' }"
        type="button"
        @click="emit('skill', '')"
      >
        全部技能
      </button>
      <button
        v-for="group in skillGroups"
        :key="group.key"
        class="chip"
        :class="{ 'chip-on': skill === group.key }"
        type="button"
        @click="emit('skill', group.key)"
      >
        {{ group.label }}
      </button>
    </div>

    <AiInput
      v-model="keyword"
      placeholder="搜标题 / 买家"
      clearable
      @input="onInput"
      @keyup.enter="emit('search', keyword)"
    />

    <div class="list">
      <div
        v-for="row in rows"
        :key="row.id"
        class="item"
        :class="{ 'item-on': row.id === currentId }"
        @click="emit('select', row.id)"
      >
        <div class="row1">
          <span class="name">{{ row.name }}</span>
          <el-tag size="small" :type="handoffTag(row.statusKey).type">{{ row.statusLabel }}</el-tag>
          <el-tag
            v-if="row.skill && row.skill !== 'general'"
            size="small"
            type="info"
            effect="plain"
          >
            {{ row.skillLabel }}
          </el-tag>
          <el-tag v-if="row.vip" size="small" type="warning" effect="plain">VIP</el-tag>
        </div>
        <div class="row2">{{ row.lastMessage || row.reason || '暂无消息' }}</div>
        <div class="row3">
          <span>{{ row.assignee ? `坐席 ${row.assignee}` : '未分配' }}</span>
          <span v-if="row.statusKey === 'pending' && row.queuePosition > 0" class="pos">
            排队第 {{ row.queuePosition }} 位
          </span>
          <span>{{ row.updatedAt.slice(5, 16) }}</span>
        </div>
      </div>
      <el-empty v-if="!rows.length && !loading" description="该筛选下暂无会话" :image-size="56" />
    </div>

    <el-pagination
      class="pager"
      size="small"
      background
      layout="sizes, prev, pager, next, total"
      :current-page="page"
      :page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      @current-change="emit('page', $event)"
      @size-change="emit('size', $event)"
    />
  </section>
</template>

<script setup lang="ts">
// 坐席工作台左栏队列：状态页签 + 服务端搜索 + 服务端分页（默认 20 / 可切 10-100）
// 对齐 页面设计 §3.2 + 前端 Skill §7；数据与流转动作由 useWorkbenchQueue 提供，组件只做展示与事件
import { onBeforeUnmount, ref } from 'vue';
import AiInput from '@/shared/components/AiInput.vue';
import { handoffTag, QUEUE_TABS } from '@/composables/useWorkbenchQueue';
import type { QueueRow } from '@/composables/useWorkbenchQueue';

defineProps<{
  rows: QueueRow[];
  currentId: string;
  total: number;
  page: number;
  size: number;
  status: string;
  skill: string;
  skillGroups?: { key: string; label: string }[];
  loading: boolean;
  demo: boolean;
}>();

const emit = defineEmits(['select', 'search', 'filter', 'skill', 'page', 'size']);

const keyword = ref('');
let timer: number | undefined;

// 输入防抖 300ms：避免每敲一个字打一次服务端搜索
const onInput = () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => emit('search', keyword.value), 300);
};

onBeforeUnmount(() => window.clearTimeout(timer));
</script>

<style scoped>
.queue {
  display: flex;
  box-sizing: border-box;

  /* 全局无 border-box 重置，padding/border 会计入 300px 栏宽之外 */
  flex: 0 0 300px;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  padding: 12px;
  background: var(--reai-card);
  border: 1px solid var(--reai-border);
  border-radius: 12px;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title {
  font-size: var(--reai-fs-body-sm);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-main);
}

.count {
  margin-left: auto;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  padding: 2px 10px;
  font-size: var(--reai-fs-micro);
  color: var(--reai-text-soft);
  cursor: pointer;
  background: transparent;
  border: 1px solid var(--reai-border);
  border-radius: 999px;
}

.chip-on {
  color: var(--reai-primary);
  background: var(--reai-primary-soft);
  border-color: var(--reai-primary);
}

/* 技能组页签比状态页签弱一档（次要筛选），避免同色抢视觉焦点 */
.skill-chips .chip {
  font-size: var(--reai-fs-micro);
}

.list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow-y: auto;
}

.item {
  padding: 8px 10px;
  cursor: pointer;
  border: 1px solid var(--reai-border);
  border-radius: 10px;
}

.item:hover {
  border-color: var(--reai-primary);
}

.item-on {
  background: var(--reai-primary-soft);
  border-color: var(--reai-primary);
}

.row1 {
  display: flex;
  align-items: center;
  gap: 6px;
}

.name {
  font-size: var(--reai-fs-body-sm);
  font-weight: var(--reai-fw-medium);
  color: var(--reai-text-main);
}

.row2 {
  margin-top: 4px;
  overflow: hidden;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row3 {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: var(--reai-fs-micro);
  color: var(--reai-text-muted);
}

/* 排队位播报（FR-7）：pending 行显示「排队第 N 位」，用在线绿强调可接 */
.pos {
  color: var(--reai-online);
}

.pager {
  flex-wrap: wrap;
  justify-content: center;

  /* 300px 窄栏下 layout 四项会溢出，允许换行而非裁切 */
  row-gap: 6px;
}

/* 窄屏纵向堆叠时 flex-basis 会变成高度约束，回退为内容高度 */
@media (width <= 1024px) {
  .queue {
    flex: none;
    width: 100%;
    min-height: 320px;
  }
}
</style>
