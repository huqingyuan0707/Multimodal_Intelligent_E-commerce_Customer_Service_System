// 经营大屏汇总（后端 P2 未就绪先占位；失败由页面回 @/mock，对齐前端 Skill §6）
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
