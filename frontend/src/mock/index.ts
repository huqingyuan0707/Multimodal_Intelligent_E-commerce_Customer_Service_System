// 演示兜底数据（后端不可用时回退，对齐前端 Skill §6；口径见页面设计 §4）
export type MockSession = {
  id: string;
  title: string;
};

export const mockSessions: MockSession[] = [
  { id: 't-demo-1', title: '演示会话：退换咨询' },
  { id: 't-demo-2', title: '演示会话：尺码推荐' },
];

// 工作台演示数据（后端队列/画像接口就绪前占位，口径见页面设计 §3.2）
export type MockWorkSession = {
  id: string;
  name: string;
  tag: string;
  vip?: boolean;
};

export const mockWorkSessions: MockWorkSession[] = [
  { id: 'w-1', name: '王女士', tag: 'VIP', vip: true },
  { id: 'w-2', name: '李先生', tag: '待处理' },
  { id: 'w-3', name: '张女士', tag: '瑕疵咨询' },
  { id: 'w-4', name: '陈先生', tag: '退款跟进' },
];

export type MockWorkMessage = {
  id: string;
  from: 'user' | 'agent';
  content: string;
};

export const mockWorkMessages: MockWorkMessage[] = [
  { id: 'm-1', from: 'user', content: '这件衣服有轻微瑕疵，能处理吗？' },
  { id: 'm-2', from: 'agent', content: '已为您识别图片中的瑕疵位置，并同步售后策略。' },
];

export type MockVlmResult = {
  category: string;
  confidence: number; // 0-1，<0.6 转人工复核
  advice: string;
};

export const mockVlmResult: MockVlmResult = {
  category: '面料勾丝',
  confidence: 0.96,
  advice: '拍照留存后申请换货',
};

export type MockCitation = {
  doc_id: string;
  title: string;
  score: number;
};

export const mockCitations: MockCitation[] = [
  { doc_id: 'policy-3.2', title: '售后政策第3.2条', score: 0.92 },
  { doc_id: 'flow-exchange', title: '换货处理流程', score: 0.87 },
];

export type MockCustomer = {
  level: string;
  order: string;
  traceId: string;
  status: string;
};

export const mockCustomer: MockCustomer = {
  level: 'VIP',
  order: '20260910',
  traceId: '8f3a91c2',
  status: '审批中',
};
