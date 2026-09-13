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
