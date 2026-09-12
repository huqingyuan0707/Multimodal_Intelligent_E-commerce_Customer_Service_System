<template>
  <div class="workbench">
    <section class="queue card">
      <h3 class="card-title">会话队列</h3>
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session"
        :class="{ active: s.id === currentId }"
        @click="select(s.id)"
      >
        <span class="avatar">{{ s.name.charAt(0) }}</span>
        <span class="name">{{ s.name }}</span>
        <el-tag v-if="s.vip" size="small" type="warning">VIP</el-tag>
        <span class="tag">{{ s.tag }}</span>
      </div>
    </section>

    <section class="chat card">
      <h3 class="card-title">当前会话：{{ currentName }}</h3>
      <div class="msgs">
        <div v-for="m in messages" :key="m.id" class="msg" :class="m.from">
          <span class="avatar" :class="m.from">{{
            m.from === 'user' ? currentName.charAt(0) : 'AI'
          }}</span>
          <p class="bubble">{{ m.content }}</p>
        </div>
        <div class="vlm">
          <p class="vlm-title">VLM 瑕疵检测</p>
          <p class="vlm-row">
            类别：{{ vlm.category }}
            <el-tag size="small" type="info">AI 回复</el-tag>
          </p>
          <p class="vlm-row">
            置信度：{{ confidenceText }}
            <el-tag size="small" type="success">拍照留存</el-tag>
          </p>
          <p class="vlm-advice">建议：{{ vlm.advice }}</p>
        </div>
        <div class="cites">
          <p class="cites-title">引用来源</p>
          <p v-for="c in citations" :key="c.doc_id" class="cite" @click="openDoc(c.doc_id)">
            {{ c.title }}
          </p>
        </div>
      </div>
      <div class="input-row">
        <AiInput v-model="draft" placeholder="输入回复…" @keyup.enter="send" />
        <AiButton @click="upload">上传图片</AiButton>
        <AiButton @click="voice">语音</AiButton>
      </div>
    </section>

    <section class="side">
      <div class="card">
        <h3 class="card-title">客户信息</h3>
        <p class="kv">会员等级：{{ customer.level }}</p>
        <svg class="trace-svg" viewBox="0 0 260 88" aria-hidden="true">
          <path
            d="M 12 62 C 60 62, 82 28, 130 28 C 178 28, 200 20, 248 20"
            fill="none"
            stroke="var(--reai-accent)"
            stroke-width="2"
            stroke-dasharray="5 4"
            opacity="0.8"
          />
          <circle
            cx="12"
            cy="62"
            r="7"
            fill="var(--reai-card-2)"
            stroke="var(--reai-accent)"
            stroke-width="2"
          />
          <circle cx="12" cy="62" r="2.5" fill="var(--reai-accent)" />
          <circle
            cx="130"
            cy="28"
            r="7"
            fill="var(--reai-card-2)"
            stroke="var(--reai-accent)"
            stroke-width="2"
          />
          <circle cx="130" cy="28" r="2.5" fill="var(--reai-accent)" />
          <circle
            cx="248"
            cy="20"
            r="7"
            fill="var(--reai-card-2)"
            stroke="var(--reai-purple)"
            stroke-width="2"
          />
          <circle cx="248" cy="20" r="2.5" fill="var(--reai-purple)" />
          <text x="12" y="84" text-anchor="middle" fill="var(--reai-text-muted)" font-size="11">
            规划
          </text>
          <text x="130" y="52" text-anchor="middle" fill="var(--reai-text-muted)" font-size="11">
            检索
          </text>
          <text x="248" y="44" text-anchor="middle" fill="var(--reai-text-muted)" font-size="11">
            决策
          </text>
        </svg>
      </div>
      <div class="card">
        <h3 class="card-title">工具调用</h3>
        <p class="kv">最近订单：{{ customer.order }}</p>
        <p class="kv mono">trace_id：{{ customer.traceId }}</p>
        <p class="kv">处理状态：{{ customer.status }}</p>
        <AiButton class="send" @click="sendTool">发送</AiButton>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
// 坐席工作台三栏（队列｜会话+VLM 卡+引用｜客户+Trace 折线图+工具），演示数据走 @/mock，真实接口就绪后替换（对齐页面设计 §3.2）
import { ElMessage, ElTag } from 'element-plus';
import { computed, ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import {
  mockCitations,
  mockCustomer,
  mockVlmResult,
  mockWorkMessages,
  mockWorkSessions,
} from '@/mock';
import type { MockWorkMessage } from '@/mock';

const sessions = mockWorkSessions;
const citations = mockCitations;
const vlm = mockVlmResult;
const customer = mockCustomer;

const currentId = ref(sessions[0]?.id ?? '');
const messages = ref<MockWorkMessage[]>([...mockWorkMessages]);
const draft = ref('');

const currentName = computed(() => sessions.find(s => s.id === currentId.value)?.name ?? '');
const confidenceText = computed(() => `${Math.round(vlm.confidence * 100)}%`);

const select = (id: string): void => {
  currentId.value = id;
};

const send = (): void => {
  const content = draft.value.trim();
  if (!content) {
    return;
  }
  messages.value = [...messages.value, { id: `u-${Date.now()}`, from: 'user', content }];
  draft.value = '';
  messages.value = [
    ...messages.value,
    { id: `a-${Date.now()}`, from: 'agent', content: '已收到，正在为你处理（演示回显）。' },
  ];
};

const upload = (): void => {
  ElMessage.info('图片上传后续接真实接口（演示占位）');
};

const voice = (): void => {
  ElMessage.info('语音输入后续补（演示占位）');
};

const openDoc = (docId: string): void => {
  ElMessage.info(`打开原文 ${docId}（演示占位，知识库就绪后跳转）`);
};

const sendTool = (): void => {
  ElMessage.success('已发送（演示占位，工具调用就绪后执行）');
};
</script>

<style scoped>
.workbench {
  display: flex;
  gap: 16px;
  min-height: calc(100vh - 92px);
}

.card {
  padding: 16px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-glass-border);
  border-radius: 12px;
  box-shadow: var(--reai-glow);
  backdrop-filter: blur(12px);
}

.card-title {
  margin: 0 0 12px;
  font-size: 15px;
  color: var(--reai-text-main);
}

.queue {
  width: 280px;
  flex-shrink: 0;
}

.session {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px;
  cursor: pointer;
  border-radius: 8px;
}

.session:hover {
  background: var(--reai-card-2);
}

.session.active {
  background: var(--reai-card-2);
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

.avatar.agent {
  font-size: 12px;
  color: var(--reai-text-on-light);
  background: var(--reai-accent);
}

.name {
  font-size: 14px;
  color: var(--reai-text-main);
}

.tag {
  margin-left: auto;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.chat {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.msgs {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.msg {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.msg.user {
  flex-direction: row-reverse;
}

.bubble {
  max-width: 70%;
  padding: 10px 14px;
  margin: 0;
  font-size: 14px;
  color: var(--reai-text-on-light);
  background: var(--reai-bubble-agent);
  border-radius: 12px;
}

.msg.user .bubble {
  color: var(--reai-nav-active);
  background: var(--reai-bubble-user);
}

.vlm {
  align-self: flex-end;
  width: 320px;
  max-width: 80%;
  padding: 12px 14px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-primary);
  border-radius: 12px;
  backdrop-filter: blur(12px);
}

.vlm-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--reai-text-main);
}

.vlm-row,
.vlm-advice {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
  font-size: 13px;
  color: var(--reai-text-main);
}

.cites {
  align-self: flex-end;
  width: 280px;
  max-width: 70%;
  padding: 12px 14px;
  background: var(--reai-glass-bg);
  border: 1px solid var(--reai-gold);
  border-radius: 12px;
  backdrop-filter: blur(12px);
}

.cites-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--reai-text-main);
}

.cite {
  margin: 6px 0;
  font-size: 13px;
  color: var(--reai-accent);
  cursor: pointer;
}

.input-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 320px;
  flex-shrink: 0;
}

.kv {
  margin: 8px 0;
  font-size: 13px;
  color: var(--reai-text-main);
}

.trace-svg {
  width: 100%;
  height: auto;
}

.mono {
  font-family: monospace;
}

.send {
  width: 100%;
  margin-top: 8px;
  background: var(--reai-gradient);
  border: none;
  color: var(--reai-nav-active);
}
</style>
