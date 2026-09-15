// WorkbenchChat 组件测试：中栏会话流（对齐页面设计 §3.1 / 画板 /-/workbench）
// 覆盖：消息行渲染 / ToolCallCard 挂同级 / 语音行事件 / 锁定态禁用 / 发送与快捷话术上抛
// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { describe, expect, it } from 'vitest';

import WorkbenchChat from './WorkbenchChat.vue';
import ToolCallCard from './ToolCallCard.vue';
import type { AgentMessage } from '@/types/agent';

const messages: AgentMessage[] = [
  { id: 'u1', role: 'user', modality: 'text', content: '帮我查下订单' },
  {
    id: 'a1',
    role: 'agent',
    modality: 'text',
    content: '已为您查询，订单在途',
    tool_calls: [{ tool: 'query_order', status: 'ok', trace_id: 'tr-1' }],
    notes: ['改址需人工确认'],
  },
  { id: 'v1', role: 'user', modality: 'voice', content: '' },
];

const baseProps = {
  name: '王小明',
  messages,
  streaming: false,
  phaseText: '',
  draft: '',
  locked: false,
  lockedHint: '会话已转人工，坐席接管后可发送',
  sendHint: '输入回复，Enter 发送',
  sendLabel: '发送',
};

const mountChat = (props: object = {}) =>
  mount(WorkbenchChat, { props: { ...baseProps, ...props }, global: { plugins: [ElementPlus] } });

describe('workbenchChat', () => {
  it('用户/Agent 消息行按角色渲染', () => {
    const wrapper = mountChat();
    expect(wrapper.find('.msg.user .bubble').text()).toBe('帮我查下订单');
    expect(wrapper.find('.msg.agent .text').text()).toContain('已为您查询');
  });

  it('Agent 消息带 tool_calls 时卡片挂消息行同级（画板挂法，非塞气泡）', () => {
    const wrapper = mountChat();
    const card = wrapper.findComponent(ToolCallCard);
    expect(card.exists()).toBe(true);
    expect(card.props('calls')).toHaveLength(1);
    expect(card.props('notes')).toEqual(['改址需人工确认']);
    // 卡片在 .msg 之外（同级），不在 .bubble 内
    expect(wrapper.find('.bubble').findComponent(ToolCallCard).exists()).toBe(false);
  });

  it('语音行：播放按钮上抛 play-voice（带消息 id）', async () => {
    const wrapper = mountChat();
    await wrapper.find('.play').trigger('click');
    expect(wrapper.emitted('play-voice')?.[0]).toEqual(['v1']);
  });

  it('锁定态：输入/图片/语音/转人工全禁用并展示提示', () => {
    const wrapper = mountChat({ locked: true });
    expect(wrapper.find('.locked').text()).toContain('会话已转人工');
    expect(wrapper.find('input').attributes('disabled')).toBeDefined();
    const handoff = wrapper.findAll('.quick').find(btn => btn.text() === '转人工');
    expect(handoff?.attributes('disabled')).toBeDefined();
  });

  it('发送按钮与 Enter 均上抛 send；快捷话术上抛 quick(key)', async () => {
    const wrapper = mountChat();
    await wrapper
      .findAll('button')
      .find(b => b.text() === '发送')!
      .trigger('click');
    expect(wrapper.emitted('send')).toHaveLength(1);
    const logistics = wrapper.findAll('.quick').find(b => b.text() === '查物流');
    await logistics!.trigger('click');
    expect(wrapper.emitted('quick')?.[0]).toEqual(['logistics']);
  });

  it('流式生成中展示阶段文案', () => {
    const wrapper = mountChat({ streaming: true, phaseText: '正在检索知识库…' });
    expect(wrapper.find('.phase').text()).toBe('正在检索知识库…');
  });
});
