<template>
  <div class="side">
    <div class="card">
      <h3 class="card-title">当前订单</h3>
      <p class="kv">订单号：{{ order.no }}</p>
      <p class="kv">
        状态：<span class="warn">{{ order.status }}</span>
      </p>
      <p class="kv">
        实付金额：<span class="money">{{ order.amount }}</span>
      </p>
    </div>
    <div class="card grow-card">
      <h3 class="card-title">AI 辅助 / 会话洞察</h3>
      <p class="hint">识别到「售后/退款」意图，建议先核对订单状态。</p>
      <p class="sub">推荐回复</p>
      <button v-for="r in suggestions" :key="r" class="suggest" @click="fill(r)">
        {{ r }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
// 右栏：订单卡＋AI 辅助（推荐回复点选填入输入框，对齐画布 sidePanel）
const emit = defineEmits(['fill']);

const order = { no: '2024091400821', status: '待发货', amount: '￥129.00' };
const suggestions = [
  '您的订单已在打包中，预计今日 18:00 前发出。',
  '如需修改地址，请在发货前告知，我帮您申请。',
];

const fill = (text: string) => {
  emit('fill', text);
};
</script>

<style scoped>
.side {
  display: flex;
  flex: 0 1 300px;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
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
  margin: 0;
  font-size: 15px;
  color: var(--reai-text-main);
}
.kv {
  margin: 8px 0;
  font-size: 13px;
  color: var(--reai-text-main);
}
.warn {
  font-weight: 600;
  color: #ff8400;
}
.money {
  font-weight: 600;
  color: #ff5a36;
}
.grow-card {
  flex: 1;
  overflow-y: auto;
}
.hint {
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  background: var(--reai-card-2);
  border-radius: 8px;
}
.sub {
  margin: 12px 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--reai-text-muted);
}
.suggest {
  display: block;
  width: 100%;
  padding: 10px;
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.5;
  text-align: left;
  cursor: pointer;
  background: var(--reai-card);
  border: 1px solid var(--reai-border);
  border-radius: 8px;
}
@media (width <= 1024px) {
  .side {
    flex: none;
    width: 100%;
  }
}
</style>
