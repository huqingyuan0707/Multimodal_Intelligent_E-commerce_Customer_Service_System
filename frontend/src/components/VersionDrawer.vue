<!-- 版本抽屉（对齐页面设计 §3.5 + FR-13.2：回滚即切回上一版本，不覆盖旧版） -->
<!-- 职责：版本历史倒序 + 回滚到指定版本（二次确认）；回滚后上抛 rolled 供父页刷新 -->
<template>
  <el-drawer :model-value="visible" :title="`版本历史 · ${title}`" size="640px" @close="close">
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="version" label="版本" width="80">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column prop="action" label="动作" width="100" />
      <el-table-column prop="actor" label="操作人" width="120" />
      <el-table-column prop="created_at" label="时间" min-width="160" />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <AiButton
            link
            size="small"
            :disabled="row.version === currentVersion"
            @click="rollback(row)"
          >
            {{ row.version === currentVersion ? '当前版' : '回滚到此版' }}
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!rows.length && !loading" description="暂无版本记录" />
  </el-drawer>
</template>

<script setup lang="ts">
// 版本抽屉：按 docId 拉版本列表；回滚先 confirm，成功上抛 rolled
import { ElMessage, ElMessageBox } from 'element-plus';
import { ref, watch } from 'vue';
import { docVersionsApi, rollbackDocApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import type { DocVersionRow } from '@/types/knowledge';

const props = defineProps<{
  visible: boolean;
  docId: string;
  title: string;
  currentVersion: number;
}>();

const emit = defineEmits(['update:visible', 'rolled']);

const loading = ref(false);
const rows = ref<DocVersionRow[]>([]);

const close = () => {
  emit('update:visible', false);
};

const load = async () => {
  if (!props.docId) return;
  loading.value = true;
  try {
    const data = (await docVersionsApi({ id: props.docId })) as {
      items: DocVersionRow[];
    };
    rows.value = data.items ?? [];
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '版本加载失败');
  } finally {
    loading.value = false;
  }
};

watch(
  () => props.visible,
  v => {
    if (v) load();
  },
);

const rollback = async (row: DocVersionRow) => {
  try {
    await ElMessageBox.confirm(`回滚到 v${row.version}（旧内容另起新版本，不覆盖）吗？`, '回滚', {
      type: 'warning',
    });
  } catch {
    return;
  }
  try {
    await rollbackDocApi({ id: props.docId, version: row.version });
    ElMessage.success('已回滚');
    emit('rolled');
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '回滚失败（需 kb 权限）');
  }
};
</script>
