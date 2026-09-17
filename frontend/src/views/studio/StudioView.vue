<template>
  <div class="page">
    <el-tabs v-model="tab">
      <el-tab-pane label="Prompt" name="prompt">
        <StudioPromptPane
          :versions="versions"
          :total="promptTotal"
          :page="promptPage"
          :size="promptSize"
          :loading="promptLoading"
          @page-change="onPromptPage"
          @size-change="onPromptSize"
          @create="onCreate"
          @publish="onPublish"
          @set-gray="onSetGray"
          @rollback="onRollback"
        />
      </el-tab-pane>
      <el-tab-pane label="工具" name="tool">
        <StudioToolPane
          :tools="toolList"
          :loading="toolLoading"
          :trialing="trialing"
          :trial-result="trialResult"
          @trial="onTrial"
        />
      </el-tab-pane>
      <el-tab-pane label="评测" name="eval">
        <StudioEvalPane
          :runs="evalRuns"
          :total="evalTotal"
          :page="evalPage"
          :size="evalSize"
          :current="evalCurrent"
          :loading="evalLoading"
          :running="evalRunning"
          @page-change="onEvalPage"
          @size-change="onEvalSize"
          @run="onEvalRun"
          @view="onEvalView"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
// Studio 三窗格编排器（唯一调用 composable 处；对齐页面设计 §3.6、design.pen Agent工作室-/studio）
// 真接口经 @/api/studio，任一失败即中文提示并置空，不编造数据；二次确认与成败提示收口在此
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import StudioEvalPane from '@/components/StudioEvalPane.vue';
import StudioPromptPane from '@/components/StudioPromptPane.vue';
import StudioToolPane from '@/components/StudioToolPane.vue';
import type { ToolCall } from '@/types/agent';
import { useStudioEval } from '@/composables/useStudioEval';
import { useStudioPrompts } from '@/composables/useStudioPrompts';
import { useStudioTools } from '@/composables/useStudioTools';

const tab = ref('prompt');

const prompts = useStudioPrompts();
const tools = useStudioTools();
const evals = useStudioEval();

const versions = computed(() => prompts.versions.value);
const promptTotal = computed(() => prompts.total.value);
const promptPage = computed(() => prompts.page.value);
const promptSize = computed(() => prompts.size.value);
const promptLoading = computed(() => prompts.loading.value);
const toolList = computed(() => tools.tools.value);
const toolLoading = computed(() => tools.loading.value);
const trialing = computed(() => tools.trialing.value);
const trialResult = ref<ToolCall | null>(null);
const evalRuns = computed(() => evals.runs.value);
const evalTotal = computed(() => evals.total.value);
const evalPage = computed(() => evals.page.value);
const evalSize = computed(() => evals.size.value);
const evalCurrent = computed(() => evals.current.value);
const evalLoading = computed(() => evals.loading.value);
const evalRunning = computed(() => evals.running.value);

// 首屏：真接口全量拉取，失败仅中文提示，各窗格保持空态
const loadAll = async () => {
  try {
    await prompts.refresh(1);
    await prompts.refreshOnline();
    await tools.refresh();
    await evals.refreshRuns(1);
    const latest = evals.runs.value[0];
    if (latest) await evals.pollRun(latest.id);
  } catch (err) {
    fail(err, '加载失败，请重试');
  }
};

const fail = (err: unknown, fallbackMsg: string) => {
  ElMessage.error(err instanceof Error ? err.message : fallbackMsg);
};

const onPromptPage = async (v: number) => {
  prompts.page.value = v;
  try {
    await prompts.refresh();
  } catch (err) {
    fail(err, '加载失败，请重试');
  }
};

const onPromptSize = async (v: number) => {
  prompts.size.value = v;
  try {
    await prompts.refresh(1);
  } catch (err) {
    fail(err, '加载失败，请重试');
  }
};

const onCreate = async (payload: { desc: string; content: string }) => {
  if (!payload.content.trim()) {
    ElMessage.warning('请先填写 Prompt 正文');
    return;
  }
  try {
    const row = await prompts.create(payload.desc, payload.content);
    ElMessage.success(`草稿 ${row.version} 已创建，评测达标后再发布`);
  } catch (err) {
    fail(err, '创建失败，请重试');
  }
};

const onPublish = async (payload: { version: string; gray: number }) => {
  try {
    const row = await prompts.publish(payload.version, payload.gray);
    ElMessage.success(
      row.status === 'online' ? `${row.version} 已全量上线` : `${row.version} 已进入灰度`,
    );
  } catch (err) {
    fail(err, '发布失败，请重试');
  }
};

const onSetGray = async (payload: { version: string; gray: number }) => {
  try {
    await prompts.setGray(payload.version, payload.gray);
    ElMessage.success('灰度比例已更新');
  } catch (err) {
    fail(err, '调整失败，请重试');
  }
};

const onRollback = async (version: string) => {
  try {
    await ElMessageBox.confirm(`确认回滚到 ${version} 吗？线上版本将被替换`, '提示');
  } catch {
    return;
  }
  try {
    const done = await prompts.rollback(version);
    ElMessage.success(`已回滚到 ${done.version}`);
  } catch (err) {
    fail(err, '回滚失败，请重试');
  }
};

const onTrial = async (payload: { name: string; argsText: string }) => {
  trialResult.value = null;
  try {
    trialResult.value = await tools.trial(payload.name, payload.argsText);
    ElMessage.success('沙箱试调完成（不写真实订单）');
  } catch (err) {
    fail(err, '试调失败，请重试');
  }
};

const onEvalRun = async (payload: { name: string; limit: number }) => {
  if (!payload.name.trim()) {
    ElMessage.warning('请先填写黄金集');
    return;
  }
  try {
    await evals.startRun(payload.name.trim(), payload.limit);
    await evals.refreshRuns(1);
    const cur = evals.current.value;
    ElMessage.success(cur && cur.pass ? '评测完成：达标可发布' : '评测完成：未达标，已禁全量发布');
  } catch (err) {
    fail(err, '评测失败，请重试');
  }
};

const onEvalPage = async (v: number) => {
  evals.page.value = v;
  try {
    await evals.refreshRuns();
  } catch (err) {
    fail(err, '加载失败，请重试');
  }
};

const onEvalSize = async (v: number) => {
  evals.size.value = v;
  try {
    await evals.refreshRuns(1);
  } catch (err) {
    fail(err, '加载失败，请重试');
  }
};

const onEvalView = async (id: string) => {
  try {
    await evals.pollRun(id);
  } catch (err) {
    fail(err, '读取失败，请重试');
  }
};

onMounted(() => {
  loadAll();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}
</style>
