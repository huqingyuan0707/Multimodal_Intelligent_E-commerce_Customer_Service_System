// 会话 store（Pinia setup 风格，对齐前端 Skill §4；只搭架子不写业务）
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api';
import { mockSessions } from '@/mock';
import type { Session } from '@/types/agent';

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([]);
  const currentId = ref<string | null>(null);

  const loadSessions = async (): Promise<void> => {
    try {
      sessions.value = await api.listSessions();
    } catch {
      sessions.value = mockSessions;
    }
  };

  const createLocalSession = (): string => {
    const id = `t-${Date.now()}`;
    sessions.value = [{ id, title: '新会话' }, ...sessions.value];
    currentId.value = id;
    return id;
  };

  return { sessions, currentId, loadSessions, createLocalSession };
});
