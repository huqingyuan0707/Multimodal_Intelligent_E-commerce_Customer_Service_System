// 经营大屏汇总（GET /screen/summary 已由后端提供；失败由页面保留上次数据并中文提示，对齐前端 Skill §6）
import { dispatch } from './http';

export const getScreenSummaryApi = async (params?: { range?: string }) => {
  const res = await dispatch({
    path: '/api/v1/screen/summary',
    params: { range: params?.range ?? 'today' },
  });
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};
