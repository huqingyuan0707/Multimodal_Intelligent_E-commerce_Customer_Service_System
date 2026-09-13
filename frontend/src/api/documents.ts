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

export const listDocumentsApi = async (params?: { page?: number; size?: number }) =>
  request({
    path: '/api/v1/documents',
    params: { page: params?.page ?? 1, size: params?.size ?? 20 },
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
