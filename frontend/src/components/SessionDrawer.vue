<template>
  <el-drawer v-model="visible" title="历史会话" size="300px">
    <SessionList
      :sessions="sessions"
      :current-id="currentId"
      :total="total"
      @new="emits('new')"
      @select="onSelect"
      @removed="emits('removed', $event)"
      @page="emits('page', $event)"
      @size="emits('size', $event)"
    />
  </el-drawer>
</template>

<script setup lang="ts">
// 会话抽屉（窄屏回退：宽屏走侧边栏常驻，本组件只在小屏经 open() 打开，对齐页面设计 §3.1）
// 列表本体复用 SessionList，选中后自动收起。
import { ElDrawer } from 'element-plus';
import { ref } from 'vue';
import SessionList from '@/components/SessionList.vue';
import type { Session } from '@/types/agent';

defineProps<{ sessions: Session[]; currentId: string | null; total: number }>();
const emits = defineEmits(['new', 'select', 'removed', 'page', 'size']);

const visible = ref(false);

const onSelect = (id: string) => {
  emits('select', id);
  visible.value = false;
};

const open = () => {
  visible.value = true;
};

const close = () => {
  visible.value = false;
};

defineExpose({ open, close });
</script>
