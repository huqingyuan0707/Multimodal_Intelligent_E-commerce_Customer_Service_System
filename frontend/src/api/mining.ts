// Mining 反馈与埋点接口（差评进待补知识候选，对齐 API 规范 §4.4/§4.13 + 页面设计 §3.1 赞踩）
import { request } from './http';

export const submitFeedbackApi = async (params: {
  message_id: string;
  vote: 'up' | 'down';
  comment?: string;
}) =>
  request({
    method: 'POST',
    path: '/api/v1/mining/feedback',
    params,
  });

// 行为埋点（发送/上传/播放/引用点击/转人工/赞踩）：fire-and-forget，失败静默不打扰买家
export const trackEventApi = async (event: string, data: Record<string, unknown> = {}) => {
  try {
    await request({
      method: 'POST',
      path: '/api/v1/governance/track',
      params: { event, data },
    });
  } catch {
    // 埋点绝不影响业务：网络/鉴权失败一律吞掉
  }
};
