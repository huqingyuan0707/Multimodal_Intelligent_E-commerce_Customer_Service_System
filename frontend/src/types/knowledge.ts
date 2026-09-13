// 知识库类型（对齐 API 规范 §4.4：列表分页对象 + 详情含正文；检索测试后端暂无接口仍禁用占位）
export type KnowledgeDoc = {
  id?: string;
  doc_id: string;
  title: string;
  sha256?: string;
  version?: number;
  skipped?: boolean;
  security_level?: string;
  channels?: string[];
  valid_from?: string;
  valid_to?: string;
  content?: string;
  created_at?: string;
};

export const DOC_LEVEL_TAG = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
} as const;

export const DOC_LEVEL_TYPE = {
  public: 'success',
  internal: 'warning',
  confidential: 'danger',
} as const;
