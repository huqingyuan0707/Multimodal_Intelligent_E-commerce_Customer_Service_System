<template>
  <div class="page">
    <div class="toolbar">
      <AiInput v-model="keyword" placeholder="按标题筛选" clearable @keyup.enter="onSearch" />
      <AiButton @click="onSearch">查询</AiButton>
      <el-upload :show-file-list="false" :http-request="upload" :disabled="uploading">
        <AiButton type="primary" :loading="uploading">上传文档</AiButton>
      </el-upload>
      <AiButton :loading="reindexing" @click="reindex">重建索引</AiButton>
      <el-tooltip content="TODO：后端暂无检索测试接口" placement="top">
        <span><AiButton disabled>检索测试</AiButton></span>
      </el-tooltip>
    </div>
    <el-empty
      v-if="!docs.length && !loading"
      description="暂无文档（后端不可用时显示演示数据）"
    />
    <el-table v-loading="loading" :data="docs" style="width: 100%">
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column label="密级" width="100">
        <template #default="{ row }"><el-tag :type="levelType(row.security_level)" size="small">{{ levelText(row.security_level) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="渠道" width="120">
        <template #default="{ row }">{{ (row.channels ?? []).join('、') || 'all' }}</template>
      </el-table-column>
      <el-table-column label="生效期" min-width="200">
        <template #default="{ row }">{{ validText(row) }}</template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <AiButton link size="small" @click="openPreview(row)">预览</AiButton>
          <AiButton link size="small" @click="openEdit(row)">编辑</AiButton>
          <AiButton link size="small" type="danger" @click="removeDoc(row)">删除</AiButton>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      layout="sizes, prev, pager, next, total"
      @size-change="loadDocs"
      @current-change="loadDocs"
    />
    <el-dialog v-model="previewVisible" :title="preview.title" width="640px">
      <div class="meta">{{ previewMeta }}</div>
      <pre class="content">{{ preview.content || '暂无正文' }}</pre>
    </el-dialog>
    <el-dialog v-model="editVisible" title="编辑文档" width="640px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="标题"><AiInput v-model="editForm.title" /></el-form-item>
        <el-form-item label="密级">
          <el-select v-model="editForm.security_level">
            <el-option label="公开" value="public" />
            <el-option label="内部" value="internal" />
            <el-option label="机密" value="confidential" />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道"><AiInput v-model="editForm.channels" placeholder="逗号分隔，如 all" /></el-form-item>
        <el-form-item label="生效起"><AiInput v-model="editForm.valid_from" placeholder="YYYY-MM-DD，可空" /></el-form-item>
        <el-form-item label="生效止"><AiInput v-model="editForm.valid_to" placeholder="YYYY-MM-DD，可空" /></el-form-item>
        <el-form-item label="正文"><AiInput v-model="editForm.content" type="textarea" :rows="12" /></el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="editVisible = false">取消</AiButton>
        <AiButton type="primary" :loading="saving" @click="saveEdit">保存（版本+1）</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 知识库：服务端分页列表 + 上传(FormData) + 重建索引 + 预览/编辑/删除；检索测试后端暂无接口仍禁用占位
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import {
  deleteDocumentApi,
  getDocumentApi,
  listDocumentsApi,
  reindexDocumentsApi,
  updateDocumentApi,
  uploadDocumentApi,
} from '@/api';
import { mockDocs } from '@/mock/knowledge';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { DOC_LEVEL_TAG } from '@/types/knowledge';
import type { KnowledgeDoc } from '@/types/knowledge';

const docs = ref<KnowledgeDoc[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const keyword = ref('');
const loading = ref(false);
const uploading = ref(false);
const reindexing = ref(false);
const saving = ref(false);

const previewVisible = ref(false);
const preview = ref<KnowledgeDoc>({ doc_id: '', title: '' });
const previewMeta = computed(() => {
  const d = preview.value;
  return `${levelText(d.security_level)} · ${(d.channels ?? []).join('、') || 'all'} · v${d.version ?? 1}`;
});

const editVisible = ref(false);
const editId = ref('');
const editForm = ref({
  title: '',
  content: '',
  security_level: 'internal',
  channels: 'all',
  valid_from: '',
  valid_to: '',
});

const levelType = (lv?: string) => {
  if (lv === 'public') return 'success';
  if (lv === 'confidential') return 'danger';
  return 'warning';
};

const levelText = (lv?: string) => {
  if (lv === 'public') return DOC_LEVEL_TAG.public;
  if (lv === 'confidential') return DOC_LEVEL_TAG.confidential;
  return DOC_LEVEL_TAG.internal;
};

const validText = (d: KnowledgeDoc) => {
  if (!d.valid_from && !d.valid_to) return '不限';
  return `${d.valid_from || '…'} ~ ${d.valid_to || '…'}`;
};

const loadDocs = async () => {
  loading.value = true;
  try {
    const res = await listDocumentsApi({ page: page.value, size: size.value, keyword: keyword.value.trim() });
    const rows = (res.items ?? res) as KnowledgeDoc[];
    docs.value = rows.filter(r => r && (r.doc_id || r.id));
    total.value = res.total ?? rows.length;
  } catch {
    const rows = keyword.value.trim()
      ? mockDocs.filter(d => d.title.includes(keyword.value.trim()))
      : mockDocs;
    docs.value = rows;
    total.value = rows.length;
    ElMessage.warning('后端不可用，已显示演示数据');
  } finally {
    loading.value = false;
  }
};

const onSearch = async () => {
  page.value = 1;
  await loadDocs();
};

const upload = async (opt: { file: File }) => {
  uploading.value = true;
  try {
    const r = await uploadDocumentApi({ file: opt.file });
    ElMessage.success(r.skipped ? '内容一致，已跳过重复入库' : '上传成功');
    await loadDocs();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '上传失败（需 kb 权限）');
  } finally {
    uploading.value = false;
  }
};

const reindex = async () => {
  reindexing.value = true;
  try {
    const r = await reindexDocumentsApi();
    ElMessage.success(`重建索引任务已提交：${r.task_id || '演示任务'}，请到任务中心跟进`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交失败');
  } finally {
    reindexing.value = false;
  }
};

const openPreview = async (row: KnowledgeDoc) => {
  try {
    preview.value = await getDocumentApi({ id: row.doc_id });
  } catch {
    preview.value = { ...row, content: row.content ?? '暂无正文（后端不可用）' };
  }
  previewVisible.value = true;
};

const openEdit = async (row: KnowledgeDoc) => {
  let detail: KnowledgeDoc = row;
  try {
    detail = await getDocumentApi({ id: row.doc_id });
  } catch {
    ElMessage.warning('详情加载失败，已用列表数据回显');
  }
  editId.value = row.doc_id;
  editForm.value = {
    title: detail.title ?? '',
    content: detail.content ?? '',
    security_level: detail.security_level ?? 'internal',
    channels: (detail.channels ?? ['all']).join(','),
    valid_from: (detail.valid_from ?? '').slice(0, 10),
    valid_to: (detail.valid_to ?? '').slice(0, 10),
  };
  editVisible.value = true;
};

const saveEdit = async () => {
  if (!editForm.value.title.trim()) {
    ElMessage.warning('标题不能为空');
    return;
  }
  saving.value = true;
  try {
    await updateDocumentApi({
      id: editId.value,
      title: editForm.value.title.trim(),
      content: editForm.value.content,
      security_level: editForm.value.security_level,
      channels: editForm.value.channels.split(',').map(s => s.trim()).filter(Boolean),
      valid_from: editForm.value.valid_from.trim(),
      valid_to: editForm.value.valid_to.trim(),
    });
    ElMessage.success('文档已更新，版本+1');
    editVisible.value = false;
    await loadDocs();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败');
  } finally {
    saving.value = false;
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

onMounted(() => {
  loadDocs();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.meta {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.content {
  max-height: 50vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
