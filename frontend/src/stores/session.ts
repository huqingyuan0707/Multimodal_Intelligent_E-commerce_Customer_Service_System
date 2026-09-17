// 会话 store（三层之 Session，Pinia setup 风格，对齐前端 Skill §4/§6 分页）
// 列表分页对象 {items,total} + 本地 t- 占位认领 + 改名/删除本地同步；加载失败置空并提示。
import { ElMessage } from 'element-plus';
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { listSessionsApi } from '@/api';
import type { Session } from '@/types/agent';

export const PAGE_SIZE = 20;

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([]);
  const total = ref(0);
  const page = ref(1);
  const size = ref(PAGE_SIZE);
  const currentId = ref<string | null>(null);

  const loadSessions = async (p = 1, s = size.value) => {
    page.value = p;
    size.value = s;
    try {
      const data = await listSessionsApi({ page: p, size: s });
      // 后端分页对象；旧数组信封兼容（联调过渡期）
      sessions.value = Array.isArray(data) ? data : (data.items ?? []);
      total.value = Array.isArray(data) ? data.length : (data.total ?? 0);
    } catch (e) {
      sessions.value = [];
      total.value = 0;
      ElMessage.error(e instanceof Error ? `加载会话失败：${e.message}` : '加载会话失败');
    }
  };

  const createLocalSession = () => {
    const id = `t-${Date.now()}`;
    sessions.value = [{ id, title: '新会话' }, ...sessions.value];
    currentId.value = id;
    return id;
  };

  // 后端会话认领：首轮流式 done 带回 session_id，用后端 id 替换本地 t- 占位并回填标题
  const adoptSession = (localId: string, backendId: string, title: string) => {
    sessions.value = sessions.value.map(s =>
      s.id === localId ? { ...s, id: backendId, title } : s,
    );
    if (currentId.value === localId) {
      currentId.value = backendId;
    }
  };

  const renameLocal = (id: string, title: string) => {
    sessions.value = sessions.value.map(s => (s.id === id ? { ...s, title } : s));
  };

  const removeLocal = (id: string) => {
    sessions.value = sessions.value.filter(s => s.id !== id);
    total.value = Math.max(0, total.value - 1);
    if (currentId.value === id) {
      currentId.value = null;
    }
  };

  return {
    sessions,
    total,
    page,
    size,
    currentId,
    loadSessions,
    createLocalSession,
    adoptSession,
    renameLocal,
    removeLocal,
  };
});
