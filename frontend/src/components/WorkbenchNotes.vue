<template>
  <section class="notes">
    <div class="head">
      <span class="title">内部备注</span>
      <el-tag size="small" type="info" effect="plain">仅坐席可见</el-tag>
      <el-tag v-if="demo" size="small" type="warning" effect="plain">演示数据</el-tag>
      <span class="count">{{ loading ? '加载中…' : `${notes.length} 条` }}</span>
    </div>

    <div class="list">
      <div v-for="note in notes" :key="note.id" class="item">
        <div class="meta">
          <span class="author">{{ note.author }}</span>
          <span>{{ fmt(note.created_at) }}</span>
        </div>
        <div class="content">{{ note.content }}</div>
      </div>
      <p v-if="!notes.length && !loading" class="empty">暂无备注，交接与复盘信息写这里</p>
    </div>

    <AiInput
      v-model="draft"
      type="textarea"
      :rows="2"
      :disabled="disabled"
      :placeholder="disabled ? '暂不可写（演示数据或未选中会话）' : '记录买家诉求 / 处理动作，买家不可见'"
    />
    <AiButton size="small" type="primary" :loading="saving" :disabled="disabled" @click="submit">
      保存备注
    </AiButton>
  </section>
</template>

<script setup lang="ts">
// 坐席内部备注卡：仅坐席可见的交接/复盘信息，展示 + 新增（不参与买家侧消息流）
// 对齐 页面设计 §3.2 + API 规范 §4.11；数据与写入由 useWorkbenchNotes 提供
import { ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { WorkbenchNote } from '@/api';

defineProps<{
  notes: WorkbenchNote[];
  loading: boolean;
  saving: boolean;
  demo: boolean;
  disabled: boolean;
}>();

const emit = defineEmits(['add']);

const draft = ref('');

const fmt = (t: string) => (t ? t.slice(5, 16).replace('T', ' ') : '');

const submit = () => {
  const text = draft.value.trim();
  if (!text) {
    return;
  }
  // 不在此清空：保存失败时草稿必须还在，由父级在成功后调 reset()
  emit('add', text);
};

// 父级在保存成功后调用（失败保留草稿，避免丢失坐席刚写的内容）
const reset = () => {
  draft.value = '';
};

defineExpose({ reset });
</script>

<style scoped>
.notes {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  /* 与 WorkbenchSide 其余区块同一种玻璃卡，避免右栏出现两种卡面 */
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 12px;
  box-shadow: var(--reai-glow);
  backdrop-filter: blur(12px);
}

.head {
  display: flex;
  align-items: center;
  gap: 6px;
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

.list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.item {
  padding: 6px 8px;
  background: var(--reai-card-2);
  border-radius: 8px;
}

.meta {
  display: flex;
  justify-content: space-between;
  font-size: var(--reai-fs-micro);
  color: var(--reai-text-muted);
}

.author {
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-soft);
}

.content {
  margin-top: 4px;
  font-size: var(--reai-fs-body-sm);
  line-height: var(--reai-lh-body);
  color: var(--reai-text-main);
  word-break: break-word;
}

.empty {
  margin: 0;
  font-size: var(--reai-fs-caption);
  color: var(--reai-text-muted);
  text-align: center;
}
</style>
