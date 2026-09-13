<template>
  <el-dialog v-model="visible" title="图片预览" width="520px" destroy-on-close>
    <div class="preview-wrap" @click="onMark">
      <el-image :src="src" fit="contain" class="preview" :preview-src-list="[src]" />
      <div v-if="box" class="bbox" :style="boxStyle" />
    </div>
    <p class="hint">点击图片标注疑似瑕疵区（可选），缩放请点图片进入灯箱</p>
    <template #footer>
      <AiButton @click="close">关闭</AiButton>
      <AiButton @click="submitMark">框选回传</AiButton>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 图片预览/缩放/标注（对齐页面设计 §5：宫格/灯箱/缩放 + 可选框选瑕疵区回传 VLM）
// 缩放复用 el-image 灯箱；标注为相对坐标框（ nach后端 bbox 百分比口径），回传由调用方落盘重检。
import { ElDialog, ElImage, ElMessage } from 'element-plus';
import { computed, ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';

const emits = defineEmits(['mark']);

const visible = ref(false);
const src = ref('');
// 标注框：相对坐标 0-1（与后端 bbox 百分比口径一致）
const box = ref({ x: 0.2, y: 0.2, w: 0.3, h: 0.3 } as { x: number; y: number; w: number; h: number } | null);

const boxStyle = computed(() => ({
  left: `${(box.value?.x ?? 0) * 100}%`,
  top: `${(box.value?.y ?? 0) * 100}%`,
  width: `${(box.value?.w ?? 0) * 100}%`,
  height: `${(box.value?.h ?? 0) * 100}%`,
}));

const open = (url: string) => {
  src.value = url;
  box.value = null;
  visible.value = true;
};

const close = () => {
  visible.value = false;
};

const onMark = (e: MouseEvent) => {
  const el = e.currentTarget as HTMLElement;
  const rect = el.getBoundingClientRect();
  const x = (e.clientX - rect.left) / rect.width;
  const y = (e.clientY - rect.top) / rect.height;
  box.value = { x: Math.max(0, x - 0.15), y: Math.max(0, y - 0.15), w: 0.3, h: 0.3 };
};

const submitMark = () => {
  if (!box.value) {
    ElMessage.warning('请先点击图片标注瑕疵区');
    return;
  }
  emits('mark', { bbox: box.value });
  ElMessage.success('标注已记录，随下一条消息回传复检');
  visible.value = false;
};

defineExpose({ open, close });
</script>

<style scoped>
.preview-wrap {
  position: relative;
  cursor: crosshair;
}

.preview {
  width: 100%;
  max-height: 50vh;
  background: var(--reai-card-2);
  border-radius: 8px;
}

.bbox {
  position: absolute;
  pointer-events: none;
  border: 2px solid var(--reai-notice);
  border-radius: 4px;
}

.hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--reai-text-muted);
}
</style>
