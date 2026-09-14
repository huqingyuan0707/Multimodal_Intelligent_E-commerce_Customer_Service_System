// 粘底跟随（职责：流式增量时用户在底部附近自动滚到底，翻历史不抢滚动）
// 链路：ChatView 列表容器 ref + scroll 事件 + draft/消息数 watch；对齐页面设计 §5 回到底部
import { nextTick, ref, watch } from 'vue';
import type { Ref } from 'vue';

// 距底部小于此值视为“在看最新”，增量时自动跟随；翻上去看历史则不动
const NEAR_BOTTOM_PX = 120;

export const useStickToBottom = (lineCount: () => number, liveText: Ref<string>) => {
  const listRef = ref<HTMLDivElement | null>(null);
  const stickBottom = ref(true);

  const scrollToBottom = () => {
    const el = listRef.value;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  };

  const onListScroll = () => {
    const el = listRef.value;
    if (!el) {
      return;
    }
    stickBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
  };

  // 发送/重进会话时主动回粘底
  const stickNow = () => {
    stickBottom.value = true;
    nextTick(() => scrollToBottom());
  };

  watch([lineCount, liveText], () => {
    if (stickBottom.value) {
      nextTick(() => scrollToBottom());
    }
  });

  return { listRef, stickBottom, scrollToBottom, onListScroll, stickNow };
};
