// useStickToBottom 单测（粘底跟随/翻历史不抢滚动，对齐前端 Skill §8）
import { describe, expect, it } from 'vitest';
import { nextTick, ref } from 'vue';
import { useStickToBottom } from './useStickToBottom';

const fakeList = (top: number, height: number, view: number) =>
  ({ scrollTop: top, scrollHeight: height, clientHeight: view }) as HTMLDivElement;

describe('useStickToBottom', () => {
  it('初始粘底，增量时滚到底', () => {
    const box = useStickToBottom(() => 1, ref(''));
    box.listRef.value = fakeList(0, 500, 200);
    box.scrollToBottom();
    expect(box.listRef.value.scrollTop).toBe(500);
  });

  it('翻到顶部后不再粘底，回到附近恢复', () => {
    const box = useStickToBottom(() => 1, ref(''));
    box.listRef.value = fakeList(0, 500, 200);
    box.onListScroll();
    expect(box.stickBottom.value).toBe(false);
    if (box.listRef.value) {
      box.listRef.value.scrollTop = 400;
    }
    box.onListScroll();
    expect(box.stickBottom.value).toBe(true);
  });

  it('stickNow 主动回粘底', async () => {
    const box = useStickToBottom(() => 1, ref(''));
    box.listRef.value = fakeList(0, 500, 200);
    box.stickBottom.value = false;
    box.stickNow();
    expect(box.stickBottom.value).toBe(true);
    await nextTick();
    expect(box.listRef.value?.scrollTop).toBe(500);
  });
});
