// 知识库类型（对齐 API 规范 §4.4：列表分页对象 + 详情含正文 + 生命周期/版本/检索测试/统计）
export type KnowledgeDoc = {
  id?: string;
  doc_id: string;
  title: string;
  sha256?: string;
  version?: number;
  skipped?: boolean;
  topic?: string;
  status?: string;
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

// 生命周期状态（FR-13.2：草稿→审核→发布→归档；只有已发布可被检索召回）
export const DOC_STATUS_TAG = {
  draft: '草稿',
  review: '审核中',
  published: '已发布',
  archived: '已归档',
} as const;

export const DOC_STATUS_TYPE = {
  draft: 'info',
  review: 'warning',
  published: 'success',
  archived: 'danger',
} as const;

export type RetrieveTestRef = {
  title: string;
  content: string;
  source: string;
  doc_id: string;
  score?: number;
  bm25?: number;
  kw?: number;
  rrf?: number;
  vector_score?: number;
};

export type RetrieveTestResult = {
  refs: RetrieveTestRef[];
  levels: string[];
  channel: string;
  filtered: {
    total_docs: number;
    expired: number;
    channel_cut: number;
    below_threshold: boolean;
  };
};

export type DocVersionRow = {
  version: number;
  title: string;
  content: string;
  sha256: string;
  actor: string;
  action: string;
  created_at: string;
};

export type DocTopicStat = {
  topic: string;
  docs: number;
  cited: number;
};

export type DocIdleRow = {
  doc_id: string;
  title: string;
  topic: string;
  created_at: string;
  days_idle: number;
};

export type DocStats = {
  total: number;
  by_status: { [status: string]: number };
  cited: { [docId: string]: number };
  topics: DocTopicStat[];
  idle_review: DocIdleRow[];
};
