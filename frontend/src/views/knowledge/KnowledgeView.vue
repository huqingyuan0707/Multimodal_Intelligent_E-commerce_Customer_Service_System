<template>
  <div class="page">
    <div class="toolbar">
      <AiInput v-model="keyword" placeholder="按标题筛选" clearable @keyup.enter="onSearch" />
      <AiButton @click="onSearch">查询</AiButton>
      <el-upload
        :show-file-list="false"
        :http-request="upload"
        :disabled="uploading"
        multiple
        :limit="10"
      >
        <AiButton type="primary" :loading="uploading">上传文档</AiButton>
      </el-upload>
      <AiButton :loading="reindexing" @click="reindex">重建索引</AiButton>
      <AiButton @click="testerVisible = true">检索测试</AiButton>
    </div>
    <el-empty v-if="!docs.length && !loading" description="暂无文档（后端不可用时显示演示数据）" />
    <el-table v-loading="loading" :data="docs" style="width: 100%">
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="topic" label="主题" width="110" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }"
          ><el-tag :type="statusType(row.status)" size="small">{{
            statusText(row.status)
          }}</el-tag></template
        >
      </el-table-column>
      <el-table-column label="密级" width="90">
        <template #default="{ row }"
          ><el-tag :type="levelType(row.security_level)" size="small">{{
            levelText(row.security_level)
          }}</el-tag></template
        >
      </el-table-column>
      <el-table-column label="渠道" width="110">
        <template #default="{ row }">{{ (row.channels ?? []).join('、') || 'all' }}</template>
      </el-table-column>
      <el-table-column label="生效期" min-width="180">
        <template #default="{ row }">{{ validText(row) }}</template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="70" />
      <el-table-column label="引用" width="70">
        <template #default="{ row }">{{ citedOf(row) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <AiButton link size="small" @click="openPreview(row)">预览</AiButton>
          <AiButton link size="small" @click="openEdit(row)">编辑</AiButton>
          <AiButton link size="small" @click="openVersions(row)">版本</AiButton>
          <AiButton
            v-if="row.status === 'draft'"
            link
            size="small"
            @click="transition(row, 'submit')"
          >
            提交审核
          </AiButton>
          <AiButton
            v-if="row.status === 'review'"
            link
            size="small"
            @click="transition(row, 'publish')"
          >
            发布
          </AiButton>
          <AiButton
            v-if="row.status === 'published'"
            link
            size="small"
            @click="transition(row, 'archive')"
          >
            归档
          </AiButton>
          <AiButton
            v-if="row.status === 'archived'"
            link
            size="small"
            @click="transition(row, 'reopen')"
          >
            重开
          </AiButton>
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
    <el-collapse v-if="stats" class="stats">
      <el-collapse-item title="引用统计（按主题聚合 + 0 引用超 30 天复核清单）" name="stats">
        <el-table :data="stats.topics" style="width: 100%">
          <el-table-column prop="topic" label="主题" min-width="140" />
          <el-table-column prop="docs" label="文档数" width="100" />
          <el-table-column prop="cited" label="被引用" width="100" />
        </el-table>
        <div class="idle-title">0 引用超 30 天（建议复核或归档）</div>
        <el-table :data="stats.idle_review" style="width: 100%">
          <el-table-column prop="title" label="标题" min-width="200" />
          <el-table-column prop="topic" label="主题" width="120" />
          <el-table-column prop="days_idle" label="闲置天数" width="100" />
        </el-table>
        <el-empty v-if="!stats.idle_review.length" description="暂无待复核文档" />
      </el-collapse-item>
    </el-collapse>
    <el-dialog v-model="previewVisible" :title="preview.title" width="640px">
      <div class="meta">{{ previewMeta }}</div>
      <pre class="content">{{ preview.content || '暂无正文' }}</pre>
    </el-dialog>
    <el-dialog v-model="editVisible" title="编辑文档" width="640px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="标题"><AiInput v-model="editForm.title" /></el-form-item>
        <el-form-item label="主题"
          ><AiInput v-model="editForm.topic" placeholder="如 退换售后，可空"
        /></el-form-item>
        <el-form-item label="密级">
          <el-select v-model="editForm.security_level">
            <el-option label="公开" value="public" />
            <el-option label="内部" value="internal" />
            <el-option label="机密" value="confidential" />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道"
          ><AiInput v-model="editForm.channels" placeholder="逗号分隔，如 all"
        /></el-form-item>
        <el-form-item label="生效起"
          ><AiInput v-model="editForm.valid_from" placeholder="YYYY-MM-DD，可空"
        /></el-form-item>
        <el-form-item label="生效止"
          ><AiInput v-model="editForm.valid_to" placeholder="YYYY-MM-DD，可空"
        /></el-form-item>
        <el-form-item label="正文"
          ><AiInput v-model="editForm.content" type="textarea" :rows="12"
        /></el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="editVisible = false">取消</AiButton>
        <AiButton type="primary" :loading="saving" @click="saveEdit">保存（版本+1）</AiButton>
      </template>
    </el-dialog>
    <RetrievalTester v-model:visible="testerVisible" />
    <VersionDrawer
      v-model:visible="versionsVisible"
      :doc-id="versionsDocId"
      :title="versionsTitle"
      :current-version="versionsCurrent"
      @rolled="onRolled"
    />
  </div>
</template>

<script setup lang="ts">
// 知识库：服务端分页列表 + 批量上传(FormData) + 重建索引 + 预览/编辑/删除
// + 生命周期流转（草稿→审核→发布→归档）+ 版本抽屉回滚 + 检索测试 + 引用统计
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { getDocumentApi, updateDocumentApi } from '@/api';
import RetrievalTester from '@/components/RetrievalTester.vue';
import VersionDrawer from '@/components/VersionDrawer.vue';
import { useKnowledgeDocs } from '@/composables/useKnowledgeDocs';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { DOC_LEVEL_TAG, DOC_STATUS_TAG, DOC_STATUS_TYPE } from '@/types/knowledge';
import type { KnowledgeDoc } from '@/types/knowledge';

const {
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
  onSearch,
  upload,
  reindex,
  transition,
  removeDoc,
} = useKnowledgeDocs();
const route = useRoute();
const saving = ref(false);
const testerVisible = ref(false);
const versionsVisible = ref(false);
const versionsDocId = ref('');
const versionsTitle = ref('');
const versionsCurrent = ref(1);

const previewVisible = ref(false);
const preview = ref<KnowledgeDoc>({ doc_id: '', title: '' });
const previewMeta = computed(() => {
  const d = preview.value;
  return `${statusText(d.status)} · ${levelText(d.security_level)} · ${(d.channels ?? []).join('、') || 'all'} · v${d.version ?? 1}`;
});

const editVisible = ref(false);
const editId = ref('');
const editForm = ref({
  title: '',
  topic: '',
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

const statusText = (st?: string) => {
  if (st === 'draft') return DOC_STATUS_TAG.draft;
  if (st === 'review') return DOC_STATUS_TAG.review;
  if (st === 'archived') return DOC_STATUS_TAG.archived;
  return DOC_STATUS_TAG.published;
};

const statusType = (st?: string) => {
  if (st === 'draft') return DOC_STATUS_TYPE.draft;
  if (st === 'review') return DOC_STATUS_TYPE.review;
  if (st === 'archived') return DOC_STATUS_TYPE.archived;
  return DOC_STATUS_TYPE.published;
};

const validText = (d: KnowledgeDoc) => {
  if (!d.valid_from && !d.valid_to) return '不限';
  return `${d.valid_from || '…'} ~ ${d.valid_to || '…'}`;
};

const citedOf = (d: KnowledgeDoc) => {
  const id = d.doc_id || d.id || '';
  return stats.value?.cited[id] ?? '—';
};

const openVersions = (row: KnowledgeDoc) => {
  versionsDocId.value = row.doc_id;
  versionsTitle.value = row.title;
  versionsCurrent.value = row.version ?? 1;
  versionsVisible.value = true;
};

const onRolled = async () => {
  await loadDocs();
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
    topic: detail.topic ?? '',
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
      topic: editForm.value.topic.trim(),
      content: editForm.value.content,
      security_level: editForm.value.security_level,
      channels: editForm.value.channels
        .split(',')
        .map(s => s.trim())
        .filter(Boolean),
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

onMounted(() => {
  // 商品管理知识同步提示「查看知识条目」→ /knowledge?keyword=xxx 直达（对齐 FR-10.1）
  const kw = route.query.keyword;
  if (typeof kw === 'string' && kw.trim()) {
    keyword.value = kw.trim();
  }
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
  overflow-wrap: break-word;
}

.stats {
  margin-top: 4px;
}

.idle-title {
  margin: 12px 0 8px;
  font-size: 13px;
  color: var(--reai-text-muted);
}
</style>
