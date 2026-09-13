// 知识库演示兜底（后端不可用时回退，保证页面可用，对齐前端 Skill §6）
import type { KnowledgeDoc } from '@/types/knowledge';

export const mockDocs: KnowledgeDoc[] = [
  { doc_id: 'demo-kb-return', title: '退换货政策（演示）', version: 1 },
  { doc_id: 'demo-kb-size', title: '尺码指南（演示）', version: 1 },
];
