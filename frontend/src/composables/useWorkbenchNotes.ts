// 坐席内部备注（/workbench/sessions/{id}/notes）：仅坐席可见，交接/复盘用，买家侧不可见
// 加载失败置空并提示（不阻塞主链路）；新增成功本地插入，不重拉全量
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { addNoteWorkbenchApi, listNotesWorkbenchApi } from '@/api';
import type { WorkbenchNote } from '@/api';

export const useWorkbenchNotes = () => {
  const notes = ref<WorkbenchNote[]>([]);
  const loading = ref(false);
  const saving = ref(false);

  const load = async (id: string) => {
    if (!id) {
      notes.value = [];
      return [];
    }
    loading.value = true;
    try {
      notes.value = ((await listNotesWorkbenchApi({ id })) ?? []) as WorkbenchNote[];
    } catch (e) {
      notes.value = [];
      ElMessage.error(e instanceof Error ? `加载备注失败：${e.message}` : '加载备注失败');
    } finally {
      loading.value = false;
    }
    return notes.value;
  };

  const add = async (id: string, content: string) => {
    const text = content.trim();
    if (!id || !text) {
      return false;
    }
    saving.value = true;
    try {
      const saved = (await addNoteWorkbenchApi({ id, content: text })) as WorkbenchNote;
      notes.value = [...notes.value, saved];
      ElMessage.success('备注已保存（仅坐席可见）');
      return true;
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '备注保存失败');
      return false;
    } finally {
      saving.value = false;
    }
  };

  const reset = () => {
    notes.value = [];
  };

  return { notes, loading, saving, load, add, reset };
};
