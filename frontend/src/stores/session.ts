// 会话 store（Pinia setup 风格，对齐前端 Skill §4；只搭架子不写业务）
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { listSessionsApi } from '@/api';
import { mockSessions } from '@/mock';
import type { Session } from '@/types/agent';

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([]);
  const currentId = ref<string | null>(null);

  const loadSessions = async () => {
    try {
      sessions.value = await listSessionsApi();
    } catch {
      sessions.value = mockSessions;
    }
  };

  const createLocalSession = () => {
    const id = `t-${Date.now()}`;
    sessions.value = [{ id, title: '新会话' }, ...sessions.value];
    currentId.value = id;
    return id;
  };

  return { sessions, currentId, loadSessions, createLocalSession };
});
