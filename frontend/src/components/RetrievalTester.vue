<!-- 检索测试器（对齐页面设计 §3.5 RetrievalTester + RAG 规范 §5 + FR-13.5） -->
<!-- 职责：运营输入 query 预览召回分数（综合/BM25/关键词/RRF/向量）与过滤原因；只读不写库 -->
<template>
  <el-dialog :model-value="visible" title="检索测试" width="860px" @close="close">
    <div class="row">
      <AiInput
        v-model="query"
        placeholder="输入买家问法，如 七天无理由退货"
        clearable
        @keyup.enter="run"
      />
      <el-select v-model="channel" style="width: 120px">
        <el-option label="全渠道" value="all" />
        <el-option label="网页" value="web" />
        <el-option label="App" value="app" />
      </el-select>
      <AiButton type="primary" :loading="testing" @click="run">测试</AiButton>
    </div>
    <div v-if="result" class="meta">
      共 {{ result.filtered.total_docs }} 篇 · 过期过滤 {{ result.filtered.expired }} · 渠道过滤
      {{ result.filtered.channel_cut }} · 可见密级 {{ (result.levels ?? []).join('、') }}
      <span v-if="result.filtered.below_threshold" class="refuse">
        未达阈值 → 前端走 2001 拒答 + 转人工
      </span>
    </div>
    <el-table v-loading="testing" :data="rows" style="width: 100%">
      <el-table-column prop="title" label="标题" min-width="180" />
      <el-table-column prop="source" label="来源块" width="140" />
      <el-table-column prop="score" label="综合" width="80" />
      <el-table-column prop="bm25" label="BM25" width="80" />
      <el-table-column prop="kw" label="关键词" width="80" />
      <el-table-column prop="rrf" label="RRF" width="80" />
      <el-table-column prop="vector_score" label="向量" width="80" />
    </el-table>
    <el-empty
      v-if="result && !rows.length && !testing"
      description="无召回（检查阈值/生效期/渠道/密级）"
    />
    <template #footer>
      <AiButton @click="close">关闭</AiButton>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 检索测试弹窗：query/渠道 → retrieveTestApi → 分数表 + 过滤计数；失败 ElMessage
import { ElMessage } from 'element-plus';
import { ref } from 'vue';
import { retrieveTestApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { RetrieveTestResult } from '@/types/knowledge';

defineProps<{ visible: boolean }>();

const emit = defineEmits(['update:visible']);

const query = ref('');
const channel = ref('all');
const testing = ref(false);
const result = ref<RetrieveTestResult | null>(null);
const rows = ref<RetrieveTestResult['refs']>([]);

const close = () => {
  emit('update:visible', false);
};

const run = async () => {
  if (!query.value.trim()) {
    ElMessage.warning('请输入测试 query');
    return;
  }
  testing.value = true;
  try {
    const data = (await retrieveTestApi({
      query: query.value.trim(),
      top_k: 5,
      channel: channel.value,
    })) as RetrieveTestResult;
    result.value = data;
    rows.value = data.refs ?? [];
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '检索测试失败');
  } finally {
    testing.value = false;
  }
};
</script>

<style scoped>
.row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.meta {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.refuse {
  color: var(--reai-notice);
}
</style>
