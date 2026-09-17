<template>
  <div>
    <p class="hint">JSON Schema / Scope / 幂等 / 超时只读展示，试调走沙箱不写真实订单</p>
    <el-table v-loading="loading" :data="tools" style="width: 100%">
      <el-table-column type="expand">
        <template #default="s">
          <div class="expand">
            <div class="expand-row">
              <span class="expand-label">说明</span>
              <span>{{ s.row.description }}</span>
            </div>
            <div class="expand-row">
              <span class="expand-label">参数</span>
              <pre class="expand-pre">{{ formatJson(s.row.params) }}</pre>
            </div>
            <div class="expand-row">
              <span class="expand-label">熔断</span>
              <pre class="expand-pre">{{ formatJson(s.row.breaker) }}</pre>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="工具" min-width="160" />
      <el-table-column prop="scope" label="Scope" width="140" />
      <el-table-column label="超时" width="100">
        <template #default="s">{{ s.row.timeout_seconds }}s</template>
      </el-table-column>
      <el-table-column label="幂等" width="90">
        <template #default="s">{{ s.row.idempotent ? '是' : '否' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="s">
          <AiButton v-permission="['ops', 'admin']" link @click="openTrial(s.row)"> 试调 </AiButton>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="trialVisible" title="沙箱试调" width="560px">
      <p class="hint">工具：{{ trialName }}（不写真实订单）</p>
      <AiInput
        v-model="trialArgs"
        type="textarea"
        :rows="5"
        placeholder='试调参数 JSON（如 {"order_id":"1"}）'
      />
      <el-alert
        v-if="trialResult?.approval_required"
        type="warning"
        show-icon
        :title="`已提交审批（单号 ${trialResult.approval_id}），账目未变动`"
        style="margin-top: 8px"
      />
      <pre v-if="trialResult" class="expand-pre" style="margin-top: 8px">{{
        formatJson(trialResult)
      }}</pre>
      <template #footer>
        <AiButton @click="trialVisible = false">关闭</AiButton>
        <AiButton type="primary" :loading="trialing" @click="submitTrial">试调</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// Studio 工具试调窗格（清单只读 + 沙箱试调对话框，对齐 API 规范 §4.12；与 ToolCallCard 同源）
// 纯展示 + 对话框本地态；试调执行上抛给 StudioView（唯一调用 composable 处），结果经 props 回显
import { ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { StudioTool, ToolCall } from '@/types/agent';

defineProps<{
  tools: StudioTool[];
  loading: boolean;
  trialing: boolean;
  trialResult: ToolCall | null;
}>();

const emit = defineEmits(['trial']);

const trialVisible = ref(false);
const trialName = ref('');
const trialArgs = ref('{}');

const formatJson = (v: unknown) => {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
};

const openTrial = (row: StudioTool) => {
  trialName.value = row.name;
  trialArgs.value = '{}';
  trialVisible.value = true;
};

const submitTrial = () => {
  emit('trial', { name: trialName.value, argsText: trialArgs.value });
};
</script>

<style scoped>
.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.expand {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 8px;
}

.expand-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.expand-label {
  flex-shrink: 0;
  width: 48px;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.expand-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
}
</style>
