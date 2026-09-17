<template>
  <el-drawer v-model="visible" title="售后单详情" size="480px">
    <el-descriptions v-if="detail" :column="1" border>
      <el-descriptions-item label="售后单ID">{{ detail.id }}</el-descriptions-item>
      <el-descriptions-item label="订单ID">{{ detail.order_id }}</el-descriptions-item>
      <el-descriptions-item label="原因">{{ detail.reason }}</el-descriptions-item>
      <el-descriptions-item label="金额">{{ formatCents(detail.amount) }}</el-descriptions-item>
      <el-descriptions-item label="状态">
        <el-tag :type="aftersaleTagOf(detail.status)" size="small">{{
          detail.status_label
        }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="质检处置">
        <el-tag :type="dispositionTagOf(detail.disposition)" size="small">{{
          detail.disposition_label
        }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="trace_id">
        <span class="mono">{{ detail.trace_id || '-' }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
    </el-descriptions>
    <div v-if="detail?.evidence?.length" class="sub-title">证据图</div>
    <div v-if="detail?.evidence?.length" class="imgs">
      <el-image
        v-for="(url, i) in detail.evidence"
        :key="i"
        :src="url"
        :preview-src-list="detail.evidence"
        :initial-index="i"
        preview-teleported
        fit="cover"
        class="big-thumb"
      />
    </div>
    <div v-if="detail" class="ops">
      <AiButton
        v-permission="['cs', 'stock', 'admin']"
        :disabled="!detail.trace_id"
        @click="emit('locate', detail)"
      >
        定位会话
      </AiButton>
      <AiButton
        v-permission="['cs', 'stock', 'admin']"
        type="primary"
        :disabled="detail.disposition !== 'pending'"
        @click="emit('dispose', detail, 'restocked')"
      >
        二次入库
      </AiButton>
      <AiButton
        v-permission="['cs', 'stock', 'admin']"
        type="warning"
        :disabled="detail.disposition !== 'pending'"
        @click="emit('dispose', detail, 'scrapped')"
      >
        报损
      </AiButton>
      <AiButton
        v-permission="['cs', 'stock', 'admin']"
        type="danger"
        :disabled="detail.disposition !== 'pending'"
        @click="emit('dispose', detail, 'returned')"
      >
        退供
      </AiButton>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
// 售后单详情抽屉：展示售后信息 + 证据图预览 + 处置/定位操作，事件上抛给调用方编排
// 对齐 FRD FR-10.4 / 页面设计 §3.13 AftersaleDrawer（订单详情内嵌售后卡的同款扩展）
import { ElDescriptions, ElDescriptionsItem, ElDrawer, ElImage, ElTag } from 'element-plus';
import AiButton from '@/shared/components/AiButton.vue';
import type { AftersaleItem } from '@/types/shop';
import { aftersaleTagOf, dispositionTagOf, formatCents } from '@/types/shop';

defineProps<{ detail: AftersaleItem | null }>();
const emit = defineEmits(['locate', 'dispose']);
const visible = defineModel<boolean>('modelValue', { required: true });
</script>

<style scoped>
.mono {
  font-family: var(--reai-font-mono);
  font-size: var(--reai-fs-caption);
}

.imgs {
  display: flex;
  flex-wrap: wrap;
  margin: 8px 0;
}

.big-thumb {
  width: 92px;
  height: 92px;
  margin-right: 8px;
  border-radius: 6px;
}

.ops {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.sub-title {
  margin: 12px 0 6px;
  font-weight: 500;
  font-size: var(--reai-fs-body);
  color: var(--reai-text);
}
</style>
