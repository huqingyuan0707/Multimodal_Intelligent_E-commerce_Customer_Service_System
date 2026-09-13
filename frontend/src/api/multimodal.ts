// 多模态接口（FR-1 图文售后 + 语音，对齐 API 规范 §4.10 + 页面设计 §3.1/§4）
// 上传走 FormData（绝不手设 Content-Type）；JSON 走 request 自动解包；id 用 encodeURIComponent。
import { request } from './http';

export const uploadAndInspectImageApi = async (params: { file: File; sessionId?: string }) => {
  const fd = new FormData();
  fd.append('file', params.file);
  fd.append('session_id', params.sessionId ?? '');
  return request({
    method: 'POST',
    path: '/api/v1/multimodal/images',
    params: fd,
  });
};

export const transcribeVoiceApi = async (params: { file: File; sessionId?: string }) => {
  const fd = new FormData();
  fd.append('file', params.file);
  fd.append('session_id', params.sessionId ?? '');
  return request({
    method: 'POST',
    path: '/api/v1/multimodal/speech/transcribe',
    params: fd,
  });
};

export const ttsConfigApi = async () =>
  request({
    path: '/api/v1/multimodal/speech/tts-config',
  });

export const synthesizeApi = async (params: { text: string; voice?: string }) =>
  request({
    method: 'POST',
    path: '/api/v1/multimodal/speech/synthesize',
    params: { text: params.text, voice: params.voice ?? '' },
  });

export const mediaUrlOf = (fileId: string) =>
  `/api/v1/multimodal/media/${encodeURIComponent(fileId)}`;
