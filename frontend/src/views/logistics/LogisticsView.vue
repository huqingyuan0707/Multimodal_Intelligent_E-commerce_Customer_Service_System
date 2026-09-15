<template>
  <div class="page">
    <div class="toolbar">
      <AiInput
        v-model="trackingNo"
        placeholder="输入运单号，如 SF123456"
        clearable
        @keyup.enter="track"
      />
      <AiButton type="primary" :loading="querying" @click="track">查询</AiButton>
      <span class="hint">查询结果会暂存成本页列表，离开本页后清空</span>
    </div>
    <el-alert
      v-if="badCount > 0"
      type="error"
      show-icon
      :title="`待回复差评 ${badCount} 条（2h SLA），请优先处理`"
    >
      <template #default>
        <AiButton link @click="goReviews">去评价页处理</AiButton>
      </template>
    </el-alert>
    <el-empty
      v-if="!ships.length && !querying"
      description="暂无查询记录，在上方输入运单号开始查询"
    />
    <el-table v-loading="querying" :data="paged" style="width: 100%" :row-class-name="rowTone">
      <el-table-column prop="company" label="快递" width="120" />
      <el-table-column prop="no" label="运单号" min-width="160" />
      <el-table-column prop="status" label="状态" min-width="140" />
      <el-table-column label="异常登记" min-width="220">
        <template #default="s">
          <el-select v-model="s.row.kind" placeholder="选择异常类型" style="width: 130px">
            <el-option v-for="k in kindOptions" :key="k.value" :label="k.label" :value="k.value" />
          </el-select>
          <AiButton
            v-permission="['cs', 'stock', 'admin']"
            link
            :loading="s.row.submitting"
            @click="submitException(s.row)"
          >
            登记异常
          </AiButton>
        </template>
      </el-table-column>
      <el-table-column label="售后单" min-width="180">
        <template #default="s">
          <span v-if="s.row.aftersale">售后单 {{ s.row.aftersale }}</span>
          <AiButton v-if="s.row.aftersale" link @click="goAftersale">去跟进</AiButton>
          <span v-else class="hint">—</span>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="ships.length"
      layout="sizes, prev, pager, next, total"
      @size-change="onSize"
      @current-change="onPage"
    />
    <p class="hint">异常登记自动建售后单；差评回复与打标在评价页（单一事实源，本页仅摘要跳转）。</p>
  </div>
</template>

<script setup lang="ts">
// 物流评价：单号查询沉淀成本页列表 + 异常登记（自动建售后单）+ 差评SLA摘要跳转评价页
// 对齐 FRD FR-10.7、页面设计 §3.17、画板 物流评价-/logistics；差评回复流归评价页所有
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { listReviewsApi, markExceptionApi, trackLogisticsApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

type ShipRow = {
  id: string;
  company: string;
  no: string;
  status: string;
  kind: string;
  submitting: boolean;
  aftersale: string;
};

// 异常类型映射表（模板禁止散落字面量，对齐前端红线枚举中文化）
const KIND_TAG = {
  stuck: '滞留',
  damaged: '破损',
  rejected: '拒收',
} as const;

type ExKind = keyof typeof KIND_TAG;

const kindOptions = (Object.keys(KIND_TAG) as ExKind[]).map(k => ({
  value: k,
  label: KIND_TAG[k],
}));

const kindLabel = (k: string) => (k in KIND_TAG ? KIND_TAG[k as ExKind] : k);

const router = useRouter();
const trackingNo = ref('');
const ships = ref<ShipRow[]>([]);
const querying = ref(false);
const page = ref(1);
const size = ref(20);
const badCount = ref(0);
// 新行进入高亮：新查到 / 刚登记异常的行闪光一次，提示数据变化
const freshId = ref('');
let freshTimer = 0;

const markFresh = (id: string) => {
  freshId.value = id;
  window.clearTimeout(freshTimer);
  freshTimer = window.setTimeout(() => {
    freshId.value = '';
  }, 900);
};

const rowTone = (data: { row: ShipRow }) => (data.row.id === freshId.value ? 'row-flash' : '');

const paged = computed(() => {
  const start = (page.value - 1) * size.value;
  return ships.value.slice(start, start + size.value);
});

const onPage = (p: number) => {
  page.value = p;
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
};

const track = async () => {
  if (!trackingNo.value.trim()) {
    ElMessage.warning('请先输入运单号再查询');
    return;
  }
  querying.value = true;
  try {
    const r = await trackLogisticsApi({ trackingNo: trackingNo.value.trim() });
    const row: ShipRow = {
      id: String(r.id ?? r.tracking_no ?? trackingNo.value.trim()),
      company: String(r.company ?? ''),
      no: String(r.tracking_no ?? trackingNo.value.trim()),
      status: String(r.status_label ?? r.status ?? '未知'),
      kind: '',
      submitting: false,
      aftersale: '',
    };
    if (!ships.value.some(s => s.id === row.id)) {
      ships.value = [row, ...ships.value];
    }
    page.value = 1;
    markFresh(row.id);
    ElMessage.success('已查到运单，结果已加入下方列表');
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '查不到该运单号，可换单号重试');
  } finally {
    querying.value = false;
  }
};

const submitException = async (row: ShipRow) => {
  if (!row.kind) {
    ElMessage.warning('请先为该运单选择异常类型');
    return;
  }
  await ElMessageBox.confirm(`登记「${kindLabel(row.kind)}」异常将自动建售后单，确认吗？`, '提示');
  row.submitting = true;
  try {
    const r = await markExceptionApi({ logisticsId: row.id, kind: row.kind });
    row.aftersale = String(r.aftersale_id ?? '');
    markFresh(row.id);
    ElMessage.success(`异常已登记，售后单 ${row.aftersale}，请到售后单跟进`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登记失败，请稍后重试');
  } finally {
    row.submitting = false;
  }
};

const goAftersale = () => {
  router.push('/aftersales');
};

const goReviews = () => {
  router.push('/reviews');
};

const loadBadSummary = async () => {
  try {
    const list = await listReviewsApi({ level: 'bad' });
    badCount.value = Array.isArray(list) ? list.filter(b => !b.replied).length : 0;
  } catch {
    badCount.value = 0;
  }
};

onMounted(() => {
  loadBadSummary();
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
  margin-bottom: 8px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

/* 目的性动效：新行进入高亮一次，提示列表有新增 */
@keyframes row-flash-in {
  0% {
    background: var(--reai-primary-soft);
  }

  100% {
    background: transparent;
  }
}

.page :deep(.row-flash) {
  animation: row-flash-in 0.9s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .page :deep(.row-flash) {
    animation: none;
  }
}
</style>
