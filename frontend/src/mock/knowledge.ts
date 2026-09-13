// 知识库演示兜底（后端不可用时回退，保证页面可用，对齐前端 Skill §6）
import type { KnowledgeDoc } from '@/types/knowledge';

export const mockDocs: KnowledgeDoc[] = [
  {
    doc_id: 'demo-kb-return',
    title: '退换货政策（演示）',
    version: 1,
    security_level: 'public',
    channels: ['all'],
    content: '签收 7 天无理由退货，质量问题 15 天内退换（演示数据）。',
  },
  {
    doc_id: 'demo-kb-size',
    title: '尺码指南（演示）',
    version: 1,
    security_level: 'public',
    channels: ['all'],
    content: '常规版按平时穿码，修身版大一码（演示数据）。',
  },
];
