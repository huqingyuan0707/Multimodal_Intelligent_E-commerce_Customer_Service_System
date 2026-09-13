<template>
  <div class="page">
    <h2>知识库</h2>
    <div class="toolbar">
      <AiInput v-model="keyword" placeholder="按标题筛选" clearable />
      <el-upload :show-file-list="false" :http-request="upload" :disabled="uploading">
        <AiButton type="primary" :loading="uploading">上传文档</AiButton>
      </el-upload>
      <AiButton :loading="reindexing" @click="reindex">重建索引</AiButton>
      <el-tooltip content="TODO：后端暂无 DELETE /documents/{id} 接口" placement="top">
        <span><AiButton disabled>删除</AiButton></span>
      </el-tooltip>
      <el-tooltip content="TODO：后端暂无检索测试接口" placement="top">
        <span><AiButton disabled>检索测试</AiButton></span>
      </el-tooltip>
    </div>
    <el-empty v-if="!filtered.length && !loading" description="暂无文档（后端不可用时显示演示数据）" />
    <el-table v-loading="loading" :data="filtered" style="width: 100%">
      <el-table-column prop="doc_id" label="文档ID" min-width="200" />
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="version" label="版本" width="100" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
// 知识库：列表 + 上传(FormData) + 重建索引；删除/版本/检索测试后端暂无接口，以禁用态 TODO 占位
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { listDocumentsApi, reindexDocumentsApi, uploadDocumentApi } from '@/api';
import { mockDocs } from '@/mock/knowledge';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { KnowledgeDoc } from '@/types/knowledge';

const docs = ref<KnowledgeDoc[]>([]);
const keyword = ref('');
const loading = ref(false);
const uploading = ref(false);
const reindexing = ref(false);

const filtered = computed(() =>
  keyword.value
    ? docs.value.filter(d => d.title.includes(keyword.value))
    : docs.value,
);

const loadDocs = async () => {
  loading.value = true;
  try {
    const rows = await listDocumentsApi();
    docs.value = (rows as KnowledgeDoc[]).filter(r => r && r.doc_id);
  } catch {
    docs.value = mockDocs;
    ElMessage.warning('后端不可用，已显示演示数据');
  } finally {
    loading.value = false;
  }
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
</style>
