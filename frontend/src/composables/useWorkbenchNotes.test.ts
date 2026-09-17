// useWorkbenchNotes 单测（真实备注列表 + 新增本地插入不重拉 + 失败置空不打断主链路，对齐前端 Skill §8）
// listNotesWorkbenchApi/addNoteWorkbenchApi 打桩；ElMessage 弹 DOM，node 环境桩掉
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { addNoteWorkbenchApi, listNotesWorkbenchApi, type WorkbenchNote } from '@/api';
import { useWorkbenchNotes } from './useWorkbenchNotes';

vi.mock('@/api', async importOriginal => {
  const mod = await importOriginal<typeof import('@/api')>();
  return { ...mod, listNotesWorkbenchApi: vi.fn(), addNoteWorkbenchApi: vi.fn() };
});

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn() },
}));

const note = (id: string, content = '已核对订单，走换货流程'): WorkbenchNote => ({
  id,
  session_id: 's-1',
  author: 'admin',
  content,
  created_at: '2026-09-14 10:30:00',
});

describe('useWorkbenchNotes', () => {
  beforeEach(() => vi.resetAllMocks());

  it('load 拉取真实备注列表', async () => {
    vi.mocked(listNotesWorkbenchApi).mockResolvedValue([note('n-1')]);
    const { notes, loading, load } = useWorkbenchNotes();
    await load('s-1');
    expect(loading.value).toBe(false);
    expect(notes.value).toHaveLength(1);
  });

  it('未选中会话直接清空不打接口', async () => {
    const { notes, load } = useWorkbenchNotes();
    await load('');
    expect(listNotesWorkbenchApi).not.toHaveBeenCalled();
    expect(notes.value).toEqual([]);
  });

  it('load 失败置空并提示（不打断主链路）', async () => {
    vi.mocked(listNotesWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const { notes, load } = useWorkbenchNotes();
    await load('s-1');
    expect(notes.value).toEqual([]);
  });

  it('add 成功后本地插入新备注，不重拉全量', async () => {
    vi.mocked(listNotesWorkbenchApi).mockResolvedValue([note('n-1')]);
    vi.mocked(addNoteWorkbenchApi).mockResolvedValue(note('n-2', '已升级为换货'));
    const { notes, add, load } = useWorkbenchNotes();
    await load('s-1');
    expect(await add('s-1', ' 已升级为换货 ')).toBe(true);
    expect(addNoteWorkbenchApi).toHaveBeenCalledWith({ id: 's-1', content: '已升级为换货' });
    expect(notes.value.map(n => n.id)).toEqual(['n-1', 'n-2']);
    expect(listNotesWorkbenchApi).toHaveBeenCalledTimes(1);
  });

  it('空内容不提交', async () => {
    const { add } = useWorkbenchNotes();
    expect(await add('s-1', '   ')).toBe(false);
    expect(addNoteWorkbenchApi).not.toHaveBeenCalled();
  });

  it('add 失败提示且不插入脏数据', async () => {
    vi.mocked(addNoteWorkbenchApi).mockRejectedValue(new Error('备注保存失败'));
    const { notes, saving, add } = useWorkbenchNotes();
    expect(await add('s-1', '已升级为换货')).toBe(false);
    expect(notes.value).toEqual([]);
    expect(saving.value).toBe(false);
  });

  it('reset 清空列表', async () => {
    vi.mocked(listNotesWorkbenchApi).mockRejectedValue(new Error('网络错误'));
    const { notes, load, reset } = useWorkbenchNotes();
    await load('s-1');
    reset();
    expect(notes.value).toEqual([]);
  });
});
