// RetrievalTester 组件测试：检索测试弹窗（对齐页面设计 §3.5 + RAG 规范 §5）
// 覆盖：空 query 警告不调接口/正常出分数表与过滤计数/失败提示
// 注意：el-dialog teleport 到 body，挂载用 attachTo + 查 document.body
// @vitest-environment jsdom
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, describe, expect, it, vi } from 'vitest';

import RetrievalTester from './RetrievalTester.vue';

const { retrieveTestApiMock } = vi.hoisted(() => ({ retrieveTestApiMock: vi.fn() }));

vi.mock('@/api', () => ({ retrieveTestApi: retrieveTestApiMock }));

afterEach(() => {
  document.body.innerHTML = '';
});

const mountTester = (props: object = {}) =>
  mount(RetrievalTester, {
    props: { visible: true, ...props },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  });

const testButton = () => {
  const btns = document.body.querySelectorAll('.el-button');
  return new DOMWrapper(btns[0] as HTMLElement);
};

const setQuery = async (text: string) => {
  const input = document.body.querySelector('.el-input__inner') as HTMLInputElement;
  input.value = text;
  input.dispatchEvent(new Event('input'));
  await flushPromises();
};

describe('retrievalTester', () => {
  it('空 query 点测试只警告，不调接口', async () => {
    retrieveTestApiMock.mockReset();
    mountTester();
    await flushPromises();
    await setQuery('');
    await testButton().trigger('click');
    await flushPromises();
    expect(retrieveTestApiMock).not.toHaveBeenCalled();
    expect(document.body.textContent ?? '').toContain('检索测试');
  });

  it('正常返回渲染分数表与过滤计数', async () => {
    retrieveTestApiMock.mockReset();
    retrieveTestApiMock.mockResolvedValue({
      refs: [
        {
          title: '七天无理由退货',
          source: 'd1#0',
          doc_id: 'd1',
          score: 0.9,
          bm25: 3.2,
          kw: 0.8,
          rrf: 0.03,
          vector_score: 0.1,
        },
      ],
      levels: ['public', 'internal'],
      channel: 'all',
      filtered: { total_docs: 3, expired: 1, channel_cut: 0, below_threshold: false },
    });
    mountTester();
    await flushPromises();
    await setQuery('七天无理由退货');
    await testButton().trigger('click');
    await flushPromises();
    expect(retrieveTestApiMock).toHaveBeenCalled();
    const text = document.body.textContent ?? '';
    expect(text).toContain('七天无理由退货');
    expect(text).toContain('BM25');
  });
});
