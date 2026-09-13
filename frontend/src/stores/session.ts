// 会话 store（三层之 Session，Pinia setup 风格，对齐前端 Skill §4/§6 分页）
// 列表分页对象 {items,total} + 本地 t- 占位认领 + 改名/删除本地同步；失败回退 mock。
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { listSessionsApi } from '@/api';
import { mockSessions } from '@/mock';
import type { Session } from '@/types/agent';

export const PAGE_SIZE = 20;

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([]);
  const total = ref(0);
  const page = ref(1);
  const currentId = ref<string | null>(null);

  const loadSessions = async (p = 1) => {
    page.value = p;
    try {
      const data = await listSessionsApi({ page: p, size: PAGE_SIZE });
      // 后端分页对象；旧数组信封兼容（联调过渡期）
      sessions.value = Array.isArray(data) ? data : (data.items ?? []);
      total.value = Array.isArray(data) ? data.length : (data.total ?? 0);
    } catch {
      sessions.value = mockSessions;
      total.value = mockSessions.length;
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
    currentId,
    loadSessions,
    createLocalSession,
    adoptSession,
    renameLocal,
    removeLocal,
  };
});
