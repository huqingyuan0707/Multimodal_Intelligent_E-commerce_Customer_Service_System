// 知识库类型（对齐 API 规范 §4.4；删除/版本/检索测试后端暂无接口，页面以 TODO 禁用态占位）
export type KnowledgeDoc = {
  doc_id: string;
  title: string;
  sha256?: string;
  version?: number;
  skipped?: boolean;
};

export const DOC_LEVEL_TAG = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
} as const;
