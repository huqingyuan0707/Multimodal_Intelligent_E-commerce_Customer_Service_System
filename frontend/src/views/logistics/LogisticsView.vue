<template>
  <div class="page">
    <h2>物流</h2>
    <div class="toolbar">
      <AiInput v-model="trackingNo" placeholder="运单号" clearable />
      <AiButton type="primary" @click="track">查询</AiButton>
    </div>
    <el-descriptions v-if="trackInfo" :column="2" border>
      <el-descriptions-item label="快递">{{ trackCompany }}</el-descriptions-item>
      <el-descriptions-item label="单号">{{ trackNo }}</el-descriptions-item>
      <el-descriptions-item label="状态">{{ trackStatus }}</el-descriptions-item>
      <el-descriptions-item label="操作">
        <el-select v-model="exKind" placeholder="异常类型" style="width: 120px">
          <el-option label="滞留" value="stuck" />
          <el-option label="破损" value="damaged" />
          <el-option label="拒收" value="rejected" />
        </el-select>
        <AiButton
          v-permission="['cs', 'stock', 'admin']"
          link
          :loading="exSubmitting"
          @click="submitException"
        >
          登记异常
        </AiButton>
      </el-descriptions-item>
    </el-descriptions>
    <p class="hint">异常登记自动建售后单，请到售后单跟进；差评处理请到评价页。</p>
  </div>
</template>

<script setup lang="ts">
// 物流：单号查询 + 异常登记（自动建售后单）；差评盘在评价页
// 对齐 FRD FR-10.7、页面设计 §3.17
import { ElMessage, ElMessageBox } from 'element-plus';
import { ref } from 'vue';
import { markExceptionApi, trackLogisticsApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

const trackingNo = ref('');
const trackInfo = ref(null);
const trackCompany = ref('');
const trackNo = ref('');
const trackStatus = ref('');
const trackId = ref('');
const exKind = ref('');
const exSubmitting = ref(false);

const track = async () => {
  if (!trackingNo.value) {
    ElMessage.warning('请输入运单号');
    return;
  }
  try {
    const r = await trackLogisticsApi({ trackingNo: trackingNo.value });
    trackInfo.value = r;
    trackCompany.value = String(r.company ?? '');
    trackNo.value = String(r.tracking_no ?? '');
    trackStatus.value = String(r.status_label ?? r.status ?? '');
    trackId.value = String(r.id ?? '');
  } catch (e) {
    trackInfo.value = null;
    ElMessage.error(e instanceof Error ? e.message : '查不到该运单号');
  }
};

const submitException = async () => {
  if (!trackId.value || !exKind.value) {
    ElMessage.warning('请先查到运单并选择异常类型');
    return;
  }
  await ElMessageBox.confirm('登记异常将自动建售后单，确认吗？', '提示');
  exSubmitting.value = true;
  try {
    const r = await markExceptionApi({ logisticsId: trackId.value, kind: exKind.value });
    ElMessage.success(`异常已登记，售后单 ${r.aftersale_id}，请到售后单跟进`);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登记失败');
  } finally {
    exSubmitting.value = false;
  }
};
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
</style>
