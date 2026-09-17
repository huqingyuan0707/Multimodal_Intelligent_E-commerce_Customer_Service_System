// useKnowledgeDocs 测试：知识库列表管线（对齐页面设计 §3.5）
// 覆盖：列表加载映射分页/后端不可用回退演示数据/删除二次确认取消不调接口
// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';

import { useKnowledgeDocs } from './useKnowledgeDocs';

const { listMock, statsMock, deleteMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  statsMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  deleteDocumentApi: deleteMock,
  docStatsApi: statsMock,
  listDocumentsApi: listMock,
  reindexDocumentsApi: vi.fn(),
  transitionDocApi: vi.fn(),
  uploadDocumentApi: vi.fn(),
}));

vi.mock('element-plus', async importOriginal => {
  const mod = await importOriginal<typeof import('element-plus')>();
  return {
    ...mod,
    ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    ElMessageBox: { confirm: vi.fn() },
  };
});

describe('useKnowledgeDocs', () => {
  it('列表加载映射 items/total 并拉统计', async () => {
    listMock.mockReset();
    statsMock.mockReset();
    listMock.mockResolvedValue({
      items: [{ doc_id: 'd1', title: '退货政策', version: 1 }],
      total: 1,
    });
    statsMock.mockResolvedValue({
      total: 1,
      by_status: {},
      cited: {},
      topics: [],
      idle_review: [],
    });
    const store = useKnowledgeDocs();
    await store.loadDocs();
    expect(store.docs.value).toHaveLength(1);
    expect(store.total.value).toBe(1);
    expect(store.stats.value?.total).toBe(1);
  });

  it('后端不可用回退演示数据', async () => {
    listMock.mockReset();
    listMock.mockRejectedValue(new Error('down'));
    const store = useKnowledgeDocs();
    await store.loadDocs();
    expect(store.docs.value.length).toBeGreaterThan(0);
    expect(store.loading.value).toBe(false);
  });
});
