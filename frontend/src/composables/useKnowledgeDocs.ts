// 知识库列表管线（对齐页面设计 §3.5）：服务端分页 + 引用统计 + 上传/重建索引/删除/生命周期流转
// 链路：KnowledgeView 组合本模块（列表数据 + 表格行动作），预览/编辑表单/抽屉状态留页面层
import { ElMessage, ElMessageBox } from 'element-plus';
import { ref } from 'vue';
import {
  deleteDocumentApi,
  docStatsApi,
  listDocumentsApi,
  reindexDocumentsApi,
  transitionDocApi,
  uploadDocumentApi,
} from '@/api';
import type { DocStats, KnowledgeDoc } from '@/types/knowledge';

const TRANSITION_NAMES: { [k: string]: string } = {
  submit: '提交审核',
  publish: '发布',
  archive: '归档',
  reopen: '重开为草稿',
};

export const useKnowledgeDocs = () => {
  const docs = ref<KnowledgeDoc[]>([]);
  const total = ref(0);
  const page = ref(1);
  const size = ref(20);
  const keyword = ref('');
  const loading = ref(false);
  const uploading = ref(false);
  const reindexing = ref(false);
  const stats = ref<DocStats | null>(null);

  const loadStats = async () => {
    try {
      stats.value = (await docStatsApi()) as DocStats;
    } catch {
      stats.value = null;
    }
  };

  const loadDocs = async () => {
    loading.value = true;
    try {
      const res = await listDocumentsApi({
        page: page.value,
        size: size.value,
        keyword: keyword.value.trim(),
      });
      const rows = (res.items ?? res) as KnowledgeDoc[];
      docs.value = rows.filter(r => r && (r.doc_id || r.id));
      total.value = res.total ?? rows.length;
      await loadStats();
    } catch (e) {
      docs.value = [];
      total.value = 0;
      stats.value = null;
      ElMessage.error(e instanceof Error ? `加载知识库失败：${e.message}` : '加载知识库失败');
    } finally {
      loading.value = false;
    }
  };

  const onSearch = async () => {
    page.value = 1;
    await loadDocs();
  };

  // 批量上传：el-upload 逐文件调 http-request，此处逐个串行入库并汇总结果
  const upload = async (opt: { file: File }) => {
    uploading.value = true;
    try {
      const r = await uploadDocumentApi({ file: opt.file });
      ElMessage.success(
        r.skipped ? `「${opt.file.name}」内容一致，已跳过` : `「${opt.file.name}」上传成功`,
      );
      await loadDocs();
    } catch (e) {
      ElMessage.error(
        e instanceof Error ? e.message : `「${opt.file.name}」上传失败（需 kb 权限）`,
      );
    } finally {
      uploading.value = false;
    }
  };

  const reindex = async () => {
    reindexing.value = true;
    try {
      const r = await reindexDocumentsApi();
      ElMessage.success(`重建索引任务已提交：${r.task_id}，请到任务中心跟进`);
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '提交失败');
    } finally {
      reindexing.value = false;
    }
  };

  const transition = async (row: KnowledgeDoc, action: string) => {
    try {
      await ElMessageBox.confirm(
        `确认对「${row.title}」执行「${TRANSITION_NAMES[action] ?? action}」吗？`,
        '状态流转',
        { type: 'warning' },
      );
    } catch {
      return;
    }
    try {
      await transitionDocApi({ id: row.doc_id, action });
      ElMessage.success('状态已更新');
      await loadDocs();
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '流转失败（发布需换人复核）');
    }
  };

  const removeDoc = async (row: KnowledgeDoc) => {
    try {
      await ElMessageBox.confirm(`确认删除文档「${row.title}」吗？`, '删除', { type: 'warning' });
    } catch {
      return;
    }
    try {
      await deleteDocumentApi({ id: row.doc_id });
      ElMessage.success('文档已删除');
      await loadDocs();
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  return {
    docs,
    total,
    page,
    size,
    keyword,
    loading,
    uploading,
    reindexing,
    stats,
    loadDocs,
    loadStats,
    onSearch,
    upload,
    reindex,
    transition,
    removeDoc,
  };
};
