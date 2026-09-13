// 文档/图片上传与知识库接口（FormData 不手设头，对齐 API 规范 §4.4；删除/版本/检索测试后端暂无接口）
import { dispatch } from './http';

export const uploadImageApi = async (params: { file: File }) => {
  const fd = new FormData();
  fd.append('file', params.file);
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/documents/upload',
    params: fd,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const listDocumentsApi = async () => {
  const res = await dispatch({ path: '/api/v1/documents' });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const uploadDocumentApi = async (params: { file: File }) => {
  const fd = new FormData();
  fd.append('file', params.file);
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/documents/upload',
    params: fd,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

export const reindexDocumentsApi = async () => {
  const res = await dispatch({
    method: 'POST',
    path: '/api/v1/documents/reindex',
    idempotent: true,
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
