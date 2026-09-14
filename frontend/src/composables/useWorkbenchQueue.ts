// 坐席工作台队列（真实 /workbench/queue：服务端分页 20 + 状态过滤 + 关键字搜索 + 流转动作）
// 失败回退 @/mock 演示数据并打 demo 标；对齐 API 规范 §4.11 + 页面设计 §3.2
import { computed, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  claimWorkbenchApi,
  handoffWorkbenchApi,
  queueWorkbenchApi,
  resolveWorkbenchApi,
  transferWorkbenchApi,
} from '@/api';
import type { WorkbenchRow } from '@/api';
import { mockWorkSessions } from '@/mock';

// 流转态 → 标签文案与色。按状态键取值（不用中文标签当键，避免后端改文案即失效）
export const HANDOFF_TAG = {
  none: { label: 'AI 接待', type: 'info' },
  pending: { label: '待接', type: 'warning' },
  handling: { label: '处理中', type: 'success' },
  resolved: { label: '已解决', type: 'primary' },
} as const;

export const handoffTag = (key: string) =>
  HANDOFF_TAG[key as keyof typeof HANDOFF_TAG] ?? HANDOFF_TAG.none;

// 队列筛选页签（open = 待接 + 处理中，工作台默认视图）
export const QUEUE_TABS = [
  { key: 'open', label: '待接入' },
  { key: 'pending', label: '待接' },
  { key: 'handling', label: '处理中' },
  { key: 'resolved', label: '已解决' },
  { key: 'none', label: 'AI 接待' },
] as const;

// 页面态队列行：后端行 → 页面消费形状（名称/标签/预览一次收口）
export type QueueRow = {
  id: string;
  name: string;
  title: string;
  statusKey: string;
  statusLabel: string;
  assignee: string;
  reason: string;
  lastMessage: string;
  updatedAt: string;
  vip: boolean;
};

const toRow = (row: WorkbenchRow): QueueRow => ({
  id: row.id,
  name: row.username || row.title || '匿名买家',
  title: row.title,
  statusKey: row.handoff_status || 'none',
  statusLabel: handoffTag(row.handoff_status || 'none').label,
  assignee: row.assignee ?? '',
  reason: row.handoff_reason ?? '',
  lastMessage: row.last_message ?? '',
  updatedAt: row.updated_at ?? '',
  vip: /vip/i.test(row.title ?? '') || row.handoff_reason === 'VIP',
});

export const useWorkbenchQueue = () => {
  const rows = ref<QueueRow[]>([]);
  const total = ref(0);
  const page = ref(1);
  const size = ref(20);
  const status = ref('open');
  const keyword = ref('');
  const loading = ref(false);
  const demo = ref(false);
  const currentId = ref('');

  const currentRow = computed(() => rows.value.find(r => r.id === currentId.value) ?? null);

  const demoRows = (): QueueRow[] =>
    mockWorkSessions.map((s, i) => ({
      id: s.id,
      name: s.name,
      title: s.tag,
      statusKey: i === 0 ? 'pending' : 'handling',
      statusLabel: handoffTag(i === 0 ? 'pending' : 'handling').label,
      assignee: i === 0 ? '' : 'admin',
      reason: '演示数据（后端队列不可用）',
      lastMessage: '演示会话预览',
      updatedAt: '',
      vip: Boolean(s.vip),
    }));

  // 拉取队列：patch 只覆盖传入项；keep=true 时当前会话离开筛选集也不切走（解决后仍可看 Trace）
  const load = async (patch?: {
    status?: string;
    keyword?: string;
    page?: number;
    size?: number;
    keep?: boolean;
  }) => {
    if (patch?.status !== undefined) status.value = patch.status;
    if (patch?.keyword !== undefined) keyword.value = patch.keyword;
    if (patch?.page !== undefined) page.value = patch.page;
    if (patch?.size !== undefined) size.value = patch.size;
    loading.value = true;
    try {
      const res = await queueWorkbenchApi({
        status: status.value,
        q: keyword.value,
        page: page.value,
        size: size.value,
      });
      rows.value = ((res?.items ?? []) as WorkbenchRow[]).map(toRow);
      total.value = Number(res?.total ?? rows.value.length);
      demo.value = false;
    } catch {
      rows.value = demoRows();
      total.value = rows.value.length;
      demo.value = true;
    } finally {
      loading.value = false;
    }
    if (!patch?.keep || !currentId.value) {
      select(rows.value.some(r => r.id === currentId.value) ? currentId.value : (rows.value[0]?.id ?? ''));
    }
    return rows.value;
  };

  const select = (id: string) => {
    currentId.value = id;
  };

  const setStatus = (key: string) => load({ status: key, page: 1 });

  const setKeyword = (word: string) => load({ keyword: word, page: 1 });

  const setPage = (next: number) => load({ page: next });

  const setSize = (next: number) => load({ size: next, page: 1 });

  // 动作统一收口：成功后重拉（keep 保当前），失败原样抛出提示，不静默
  const run = async (task: () => unknown, okMsg: string) => {
    try {
      await task();
      ElMessage.success(okMsg);
      await load({ keep: true });
      return true;
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '操作失败');
      return false;
    }
  };

  const claim = async (id?: string) => {
    const target = id ?? currentId.value;
    if (!target) {
      return false;
    }
    return run(() => claimWorkbenchApi({ id: target }), '已认领，可开始代回');
  };

  const transfer = async (id?: string) => {
    const target = id ?? currentId.value;
    if (!target) {
      return false;
    }
    let assignee = '';
    try {
      const res = await ElMessageBox.prompt('输入接收会话的坐席用户名', '转接会话', {
        inputPattern: /\S+/,
        inputErrorMessage: '坐席用户名不能为空',
        confirmButtonText: '确认转接',
        cancelButtonText: '取消',
      });
      assignee = 'value' in res ? String(res.value ?? '').trim() : '';
    } catch {
      return false;
    }
    if (!assignee) {
      return false;
    }
    return run(() => transferWorkbenchApi({ id: target, assignee }), `已转接给 ${assignee}`);
  };

  const resolve = async (id?: string, conclusion?: string) => {
    const target = id ?? currentId.value;
    if (!target) {
      return false;
    }
    let text = conclusion ?? '';
    if (conclusion === undefined) {
      try {
        const res = await ElMessageBox.prompt('填写解决小结（买家不可见，用于质检复盘）', '解决会话', {
          inputPlaceholder: '如：已按 15 天质量问题换货处理',
          confirmButtonText: '确认解决',
          cancelButtonText: '取消',
        });
        text = 'value' in res ? String(res.value ?? '').trim() : '';
      } catch {
        return false;
      }
    }
    return run(() => resolveWorkbenchApi({ id: target, conclusion: text }), '会话已解决归档');
  };

  // 转人工（买家侧请求人工 / 坐席手动挂起队列）
  const handoff = async (id?: string, reason?: string) => {
    const target = id ?? currentId.value;
    if (!target) {
      return false;
    }
    return run(() => handoffWorkbenchApi({ id: target, reason: reason ?? '坐席挂起待人工' }), '已转入待接队列');
  };

  return {
    rows,
    total,
    page,
    size,
    status,
    keyword,
    loading,
    demo,
    currentId,
    currentRow,
    load,
    select,
    setStatus,
    setKeyword,
    setPage,
    setSize,
    claim,
    transfer,
    resolve,
    handoff,
  };
};
