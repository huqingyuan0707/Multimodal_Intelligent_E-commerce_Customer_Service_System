<template>
  <div class="session-list">
    <AiButton class="new" @click="emits('new')">新会话</AiButton>
    <div
      v-for="s in sessions"
      :key="s.id"
      class="sess"
      :class="{ active: s.id === currentId }"
      @click="emits('select', s.id)"
    >
      <span class="title">{{ s.title }}</span>
      <span v-if="s.message_count" class="count">{{ s.message_count }} 条</span>
      <span class="ops">
        <span class="op" @click.stop="renameSession(s.id)">改名</span>
        <span class="op danger" @click.stop="removeSession(s.id)">删除</span>
      </span>
    </div>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      layout="sizes, prev, pager, next, total"
      :total="total"
      @current-change="onPage"
      @size-change="onSize"
    />
  </div>
</template>

<script setup lang="ts">
// 会话列表本体（三层之 Session，对齐页面设计 §3.1：分页默认 20 + 改名 + 删除 + 消息数）
// 侧边栏与抽屉复用同一份：改名/删除直调接口 + 同步 store（破坏操作先 confirm），
// 选中/新建/翻页经 emits 交页面（页面管消息区与恢复翻页）。
import { ElMessage, ElMessageBox, ElPagination } from 'element-plus';
import { ref } from 'vue';
import { deleteSessionApi, renameSessionApi } from '@/api';
import { useSessionStore } from '@/stores/session';
import AiButton from '@/shared/components/AiButton.vue';
import type { Session } from '@/types/agent';

defineProps<{ sessions: Session[]; currentId: string | null; total: number }>();
const emits = defineEmits(['new', 'select', 'removed', 'page', 'size']);

const page = ref(1);
const size = ref(20);
const sessionStore = useSessionStore();

const onPage = (p: number) => {
  page.value = p;
  emits('page', p);
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
  emits('size', s);
};

const renameSession = async (id: string) => {
  try {
    const { value } = await ElMessageBox.prompt('新标题（≤20 字）', '重命名会话', {
      inputValue: sessionStore.sessions.find(s => s.id === id)?.title ?? '',
    });
    const title = String(value ?? '').trim();
    if (!title) {
      return;
    }
    await renameSessionApi({ id, title });
    sessionStore.renameLocal(id, title.slice(0, 20));
    ElMessage.success('标题已更新');
  } catch {
    ElMessage.info('已取消重命名');
  }
};

const removeSession = async (id: string) => {
  try {
    await ElMessageBox.confirm('删除后消息一并遗忘，不可恢复', '删除会话');
  } catch {
    return;
  }
  try {
    await deleteSessionApi({ id });
    sessionStore.removeLocal(id);
    emits('removed', id);
    ElMessage.success('会话已删除');
  } catch {
    ElMessage.error('删除失败');
  }
};
</script>

<style scoped>
.session-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.new {
  width: 100%;
  margin-bottom: 8px;
}

.sess {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 10px;
  margin-bottom: 4px;
  font-size: var(--reai-fs-body);
  line-height: var(--reai-lh-tight);
  cursor: pointer;
  color: var(--reai-text-main);
  border-radius: 8px;
}

.sess:hover {
  background: var(--reai-card-2);
}

.sess.active {
  background: var(--reai-card-2);
}

.title {
  flex: 1;
  overflow: hidden;
  font-weight: var(--reai-fw-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  font-size: var(--reai-fs-caption);
  line-height: var(--reai-lh-tight);
  color: var(--reai-text-soft);
  white-space: nowrap;
}

.ops {
  display: flex;
  gap: 6px;
}

.op {
  font-size: var(--reai-fs-caption);
  font-weight: var(--reai-fw-medium);
  line-height: var(--reai-lh-tight);
  color: var(--reai-accent);
  white-space: nowrap;
}

.op.danger {
  color: var(--reai-notice);
}
</style>
