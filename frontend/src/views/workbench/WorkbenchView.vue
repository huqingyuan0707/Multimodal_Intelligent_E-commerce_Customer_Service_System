<template>
  <div class="workbench">
    <!-- 左：会话队列（状态页签＋服务端搜索/分页；数据与流转动作由 useWorkbenchQueue 提供） -->
    <WorkbenchQueue
      :rows="queueRows"
      :current-id="currentId"
      :total="total"
      :page="page"
      :size="size"
      :status="status"
      :loading="queueLoading"
      :demo="queueDemo"
      @select="pickRow"
      @search="setKeyword"
      @filter="setStatus"
      @page="setPage"
      @size="setSize"
    />

    <!-- 中：当前会话（顶栏流转动作＋消息流＋快捷话术＋输入行，画布 chatPanel） -->
    <section class="chat card">
      <div class="chat-head">
        <span class="avatar">{{ currentName.charAt(0) || '客' }}</span>
        <span class="meta">
          <span class="name">{{ currentName }}</span>
          <span class="online">{{ statusText }}</span>
        </span>
        <el-tag v-if="traceDemo" size="small" type="warning" effect="plain">演示消息</el-tag>
        <AiButton
          v-if="currentRow?.statusKey === 'pending'"
          type="primary"
          @click="claim()"
        >
          认领
        </AiButton>
        <template v-else-if="isMine">
          <AiButton @click="transfer()">转接</AiButton>
          <AiButton type="primary" @click="resolve()">解决</AiButton>
        </template>
        <AiButton v-else-if="currentRow" @click="handoff()">
          {{ currentRow.statusKey === 'resolved' ? '重新转人工' : '转人工' }}
        </AiButton>
      </div>

      <WorkbenchChat
        :name="currentName"
        :messages="messages"
        :streaming="streaming"
        :phase-text="phaseText"
        :draft="draft"
        :locked="locked"
        :locked-hint="lockedHint"
        :send-hint="sendHint"
        :send-label="sendLabel"
        @update:draft="draft = $event"
        @send="send"
        @quick="applyQuick"
        @image="pickImage"
        @voice="recordVoice"
        @play-voice="playVoice"
        @open-doc="openDoc"
      />
    </section>

    <!-- 右：订单卡＋本轮 Trace＋上下文用量＋AI 辅助＋内部备注（插槽注入，买家不可见） -->
    <WorkbenchSide
      :order="sideOrder"
      :demo="sideDemo"
      :traces="sessionTraces"
      :usage="sideUsage"
      @fill="draft = $event"
    >
      <!-- key 绑 currentId：切会话即重挂，清掉上一会话未提交的备注草稿 -->
      <WorkbenchNotes
        ref="notesRef"
        :key="currentId"
        :notes="notes"
        :loading="notesLoading"
        :saving="notesSaving"
        :demo="notesDemo"
        :disabled="notesDisabled"
        @add="saveNote"
      />
    </WorkbenchSide>
  </div>
</template>

<script setup lang="ts">
// 坐席工作台三栏编排（FR-7 转人工闭环）：队列流转 ▸ 会话流（坐席代回 / AI 代答 / 只读围观）▸ 订单+Trace+备注
// 链路：WorkbenchView → useWorkbenchQueue / useWorkbenchTrace / useWorkbenchNotes / useWorkbenchSide → 组件
// 对齐：页面设计 §3.2 + API 规范 §4.11；队列/Trace/备注失败各自回退演示并挂 demo 标，不阻塞使用
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref, watch } from 'vue';
import { replyWorkbenchApi } from '@/api';
import WorkbenchChat from '@/components/WorkbenchChat.vue';
import WorkbenchNotes from '@/components/WorkbenchNotes.vue';
import WorkbenchQueue from '@/components/WorkbenchQueue.vue';
import WorkbenchSide from '@/components/WorkbenchSide.vue';
import { useAgentStream } from '@/composables/useAgentStream';
import { useWorkbenchNotes } from '@/composables/useWorkbenchNotes';
import { useWorkbenchQueue } from '@/composables/useWorkbenchQueue';
import { useWorkbenchSide } from '@/composables/useWorkbenchSide';
import { useWorkbenchTrace } from '@/composables/useWorkbenchTrace';
import AiButton from '@/shared/components/AiButton.vue';
import { useUserStore } from '@/stores/user';

// 流式阶段中文映射（后端 phase 原语：retrieving/generating/validating）
const PHASE_TAG = {
  retrieving: '检索中…',
  generating: '生成中…',
  validating: '校验引用中…',
} as const;

// 快捷话术：键 → 填入文案（handoff 是动作不是话术，见 applyQuick）
const QUICK_TEXT = {
  logistics: '帮我查一下这笔订单的物流进度',
  refund: '商品有点问题，想申请退换货',
} as const;

// —— 队列与流转动作（失败自动回退演示并挂标；确认框/提示内置在 composable）——
const {
  rows: queueRows,
  total,
  page,
  size,
  status,
  loading: queueLoading,
  demo: queueDemo,
  currentId,
  currentRow,
  load: loadQueue,
  select: pickRow,
  setStatus,
  setKeyword,
  setPage,
  setSize,
  claim,
  transfer,
  resolve,
  handoff,
} = useWorkbenchQueue();

// —— 会话流 / Trace / 内部备注（三者同口径绑定 currentId）——
const { messages, context, demo: traceDemo, load: loadTrace, append } = useWorkbenchTrace();
const {
  notes,
  loading: notesLoading,
  saving: notesSaving,
  demo: notesDemo,
  load: loadNotes,
  add: addNote,
  reset: resetNotes,
} = useWorkbenchNotes();
const { sideOrder, sideDemo, sessionTraces, sideUsage } = useWorkbenchSide(messages, context);

const draft = ref('');
const notesRef = ref<InstanceType<typeof WorkbenchNotes> | null>(null);
const stream = useAgentStream();
const streaming = stream.streaming;
const me = useUserStore().user?.name ?? '';

// 本人认领的 handling 会话才可代回；他人处理/已解决只读围观
const isMine = computed(
  () => currentRow.value?.statusKey === 'handling' && currentRow.value?.assignee === me,
);

// AI 接待会话不锁：坐席可触发 AI 代答；pending 需先认领；handling 仅本人；resolved 归档只读
const locked = computed(() => {
  const r = currentRow.value;
  if (!currentId.value || !r) return true;
  if (r.statusKey === 'none') return false;
  if (r.statusKey === 'pending') return true;
  return !isMine.value;
});

const lockedHint = computed(() => {
  const r = currentRow.value;
  if (!r) return '请在左侧选择一个会话';
  if (r.statusKey === 'pending') return '买家请求人工，请先「认领」再回复';
  if (r.statusKey === 'resolved') return '会话已解决归档，只读查看';
  return `已由 ${r.assignee} 认领，当前只读围观`;
});

const sendLabel = computed(() => (isMine.value ? '代回买家' : 'AI 代答'));
const sendHint = computed(() =>
  isMine.value ? '代回内容买家侧即时可见' : '发送后走 AI 流式代答（引用/检测卡随回执展示）',
);

const statusText = computed(() => {
  const r = currentRow.value;
  if (!r) return '在线 · 咨询中';
  if (r.statusKey === 'handling') {
    return r.assignee === me ? '处理中 · 我正在服务' : `处理中 · ${r.assignee} 认领（只读围观）`;
  }
  if (r.statusKey === 'pending') return '待接 · 买家请求人工';
  if (r.statusKey === 'resolved') return '已解决归档';
  return 'AI 接待中';
});

const currentName = computed(() => currentRow.value?.name ?? '');
const notesDisabled = computed(() => !currentId.value || queueDemo.value);

const phaseText = computed(() => {
  const p = stream.phase.value;
  if (stream.streaming.value && p in PHASE_TAG) return PHASE_TAG[p as keyof typeof PHASE_TAG];
  if (stream.streaming.value) return p || '请求中…';
  return '';
});

// 切会话联动：停流 + 重拉 Trace/备注（队列 load 自动选首行也会触发本 watch）
watch(currentId, id => {
  if (stream.streaming.value) stream.stop();
  draft.value = '';
  loadTrace(id);
  if (queueDemo.value) resetNotes();
  else loadNotes(id);
});

const send = async () => {
  const content = draft.value.trim();
  if (!content || streaming.value || locked.value) return;
  const id = currentId.value;
  draft.value = '';
  // 演示数据：后端队列不可用，本地回显避免必然 404 报错刷屏
  if (queueDemo.value) {
    append({ id: `d-${Date.now()}`, role: 'agent', modality: 'text', content });
    return;
  }
  // 本人认领会话：坐席代回落 agent 行（买家历史即见），不烧 AI
  if (isMine.value) {
    try {
      const saved = (await replyWorkbenchApi({ id, content })) as { content?: string };
      append({
        id: `cs-${Date.now()}`,
        role: 'agent',
        modality: 'text',
        content: saved?.content || content,
      });
    } catch (e) {
      draft.value = content;
      ElMessage.error(e instanceof Error ? e.message : '代回失败，请稍后重试');
    }
    return;
  }
  // AI 接待会话：真流式代答（引用/检测卡/上下文用量随 done 落到该条消息）
  const key = `c-${Date.now()}`;
  append({ id: key, role: 'user', modality: 'text', content });
  const target = `a-${key}`;
  append({ id: target, role: 'agent', modality: 'text', content: '' });
  await stream.start(content, { threadId: id, clientMsgId: key });
  const final = stream.toMessage(target);
  messages.value = messages.value.map(m => (m.id === target ? { ...final, id: target } : m));
  if (stream.error.value) ElMessage.error(stream.error.value);
};

const applyQuick = (key: string) => {
  if (key === 'handoff') {
    handoff();
    return;
  }
  draft.value = key in QUICK_TEXT ? QUICK_TEXT[key as keyof typeof QUICK_TEXT] : '';
};

// 备注保存成功才清草稿；失败保留，避免坐席白写一段
const saveNote = async (text: string) => {
  if (await addNote(currentId.value, text)) notesRef.value?.reset();
};

const pickImage = () => ElMessage.info('图片上传后续接多模态接口（演示占位，≤9张/单张≤10M）');
const recordVoice = () => ElMessage.info('按住录音 ≤60s（演示占位）');
const playVoice = (id: string) => ElMessage.info(`播放语音 ${id}（演示占位）`);
const openDoc = (source: string) => ElMessage.info(`打开原文 ${source}（知识库预览就绪后跳转）`);

onMounted(() => {
  // load 内部自动选首行 → watch 触发 Trace/备注加载；队列为空时中栏留白
  loadQueue();
});
</script>

<style scoped>
.workbench {
  display: flex;
  gap: 16px;
  height: 100%;
  min-height: 0;
}
.card {
  padding: 16px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 12px;
  box-shadow: var(--reai-glow);
  backdrop-filter: blur(12px);
}
.name,
.online {
  line-height: var(--reai-lh-tight);
}
.avatar {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 14px;
  color: var(--reai-nav-active);
  background: var(--reai-primary);
  border-radius: 50%;
}
.name {
  font-size: var(--reai-fs-body-sm);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-text-main);
}
.chat {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.chat-head {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--reai-border);
}
.meta {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.online {
  font-size: var(--reai-fs-micro);
  font-weight: var(--reai-fw-semibold);
  color: var(--reai-online);
}
@media (width <= 1024px) {
  .workbench {
    flex-direction: column;
    overflow-y: auto;
  }
  .chat {
    min-height: 60vh;
  }
}
</style>
