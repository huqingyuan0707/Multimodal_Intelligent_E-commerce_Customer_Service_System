// 文档/图片上传与知识库接口（FormData 不手设头，对齐 API 规范 §4.4；分页默认 20）
import { request } from './http';

export const uploadImageApi = async (params: { file: File }) => {
  const fd = new FormData();
  fd.append('file', params.file);
  return request({
    method: 'POST',
    path: '/api/v1/documents/upload',
    params: fd,
  });
};

export const listDocumentsApi = async (params?: {
  page?: number;
  size?: number;
  keyword?: string;
}) =>
  request({
    path: '/api/v1/documents',
    params: { page: params?.page ?? 1, size: params?.size ?? 20, keyword: params?.keyword ?? '' },
  });

export const uploadDocumentApi = async (params: { file: File }) => {
  const fd = new FormData();
  fd.append('file', params.file);
  return request({
    method: 'POST',
    path: '/api/v1/documents/upload',
    params: fd,
  });
};

export const getDocumentApi = async (params: { id: string }) =>
  request({
    path: `/api/v1/documents/${encodeURIComponent(params.id)}`,
  });

export const updateDocumentApi = async (params: {
  id: string;
  title: string;
  content?: string;
  topic?: string;
  security_level?: string;
  channels?: string[];
  valid_from?: string;
  valid_to?: string;
}) =>
  request({
    method: 'PUT',
    path: `/api/v1/documents/${encodeURIComponent(params.id)}`,
    params: {
      title: params.title,
      content: params.content ?? '',
      topic: params.topic ?? '',
      security_level: params.security_level ?? 'internal',
      channels: params.channels ?? ['all'],
      valid_from: params.valid_from ?? '',
      valid_to: params.valid_to ?? '',
    },
    idempotent: true,
  });

export const deleteDocumentApi = async (params: { id: string }) =>
  request({
    method: 'DELETE',
    path: `/api/v1/documents/${encodeURIComponent(params.id)}`,
  });

export const reindexDocumentsApi = async () =>
  request({
    method: 'POST',
    path: '/api/v1/documents/reindex',
    idempotent: true,
  });

// 检索测试：运营输入 query 预览召回分数与过滤原因（对齐 RAG 规范 §5 + FR-13.5）
export const retrieveTestApi = async (params: {
  query: string;
  top_k?: number;
  channel?: string;
}) =>
  request({
    method: 'POST',
    path: '/api/v1/documents/retrieve-test',
    params: {
      query: params.query,
      top_k: params.top_k ?? 5,
      channel: params.channel ?? 'all',
    },
  });

// 版本历史倒序（版本抽屉数据源）
export const docVersionsApi = async (params: { id: string }) =>
  request({
    path: `/api/v1/documents/${encodeURIComponent(params.id)}/versions`,
  });

// 回滚到历史版本（旧内容另起新版本，需 kb 权限）
export const rollbackDocApi = async (params: { id: string; version: number }) =>
  request({
    method: 'POST',
    path: `/api/v1/documents/${encodeURIComponent(params.id)}/rollback`,
    params: { version: params.version },
    idempotent: true,
  });

// 生命周期流转（submit/publish/archive/reopen，需 kb 权限；发布需换人复核）
export const transitionDocApi = async (params: { id: string; action: string }) =>
  request({
    method: 'POST',
    path: `/api/v1/documents/${encodeURIComponent(params.id)}/transition`,
    params: { action: params.action },
    idempotent: true,
  });

// 引用统计（按主题聚合引用命中 + 0 引用超 30 天复核清单）
export const docStatsApi = async () =>
  request({
    path: '/api/v1/documents/stats',
  });
