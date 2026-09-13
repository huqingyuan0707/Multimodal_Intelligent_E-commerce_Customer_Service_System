// 统一请求分发层（API 唯一 fetch 出口，对齐 API 规范 §1 信封 + 前端 Skill §3）
// dispatch：Token/Content-Type/幂等键/401 中央回跳收口；GET/DELETE 自动拼 query，POST/PUT 自动 JSON，FormData 直传不手设头。
// request：在 dispatch 上再包一层自动解包（code!==0 按错误码转中文抛错），新接口优先用它；存量 dispatch 调用触碰即迁。
// 类型口径（AGENTS.md §4 宽松推断）：信封 data 取 any，接口层不写返回类型与泛型，由调用方上下文推断。
export type Envelope = {
  code: number;
  msg: string;
  data: any;
  trace_id?: string;
};

export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

// 401 中央处理（HTTP 401 或业务码 1002）：清登录态回登录页，禁止各页面自写跳转。
// 已在 /login 时只清态不跳转：否则登录失败会被整页刷新，错误提示一闪而过（幂等防回环）。
export const handle401 = () => {
  sessionStorage.removeItem('reai_token');
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
};

const fail = (msg: string, code: number) => {
  const err = new Error(msg) as Error & { code: number };
  err.code = code;
  return err;
};

// 错误码转中文（对齐 API 规范 §2 号段；后端 msg 已中文，此表兜底未知码/网络异常，前端 ElMessage 直接展示）
export const ERROR_MESSAGES = {
  1001: '请求参数有误，请检查后重试',
  1002: '未登录或登录已过期，请重新登录',
  1003: '权限不足，请联系管理员',
  1004: '资源不存在或已过期',
  1005: '配额已用完，请联系管理员',
  1006: '操作太频繁，请稍后再试',
  2000: '模型调用失败，已降级为片段摘要',
  2001: '暂未查到权威政策，已为你转人工',
  2002: '对话受限，请稍后再试',
  2003: '内容不合规，已拦截',
  2004: '图片过大，请压缩后重试',
  3001: '订单不存在',
  3002: '无权操作该订单',
  3003: '该操作需要审批，已提交审批单',
  3004: '库存不足',
  3005: '订单状态不允许该操作',
  3006: '优惠券已领完',
  3007: '风控拦截，已转人工复核',
  4001: '任务不存在或已过期',
  4002: '任务超时，请重试',
  4003: '该操作需要审批',
  4004: '审批未通过，原数据保持不变',
  5000: '系统繁忙，请稍后重试',
  5001: '上游服务异常，请稍后重试',
  5002: '模型服务不可用，已降级为片段摘要',
} as const;

export const errorMessage = (code: number, fallback: string) => {
  const table = ERROR_MESSAGES as unknown as object as { [k: number]: string | undefined };
  return table[code] ?? fallback ?? '操作失败，请稍后重试';
};

export type DispatchOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  systemId?: string; // 预留：子系统编号（当前单一后端，不参与路由）
  path: string;
  params?: object | FormData; // GET/DELETE 拼 query；POST/PUT 转 JSON；FormData 直传
  idempotent?: boolean; // 写操作置 true：自动带 Idempotency-Key（文档 §4.7）
  idemKey?: string; // 显式幂等键（如发券 promo+用户+时间戳），优先于自动生成
  authRedirect?: boolean; // false 供登录接口自身使用：失败抛给页面提示，不触发 handle401
};

const isQueryMethod = (method: string) => method === 'GET' || method === 'DELETE';

// query 组装：跳过 undefined/null，保留 ''（与既有接口的空串筛选口径一致）
const buildUrl = (opt: DispatchOptions, method: string) => {
  const { path, params } = opt;
  const url = `${API_BASE}${path}`;
  if (!isQueryMethod(method) || !params || params instanceof FormData) {
    return url;
  }
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null) {
      q.set(k, String(v));
    }
  });
  const qs = q.toString();
  return qs ? `${url}${path.includes('?') ? '&' : '?'}${qs}` : url;
};

// 头组装：JSON 体才带 Content-Type（FormData 绝不手设，交给浏览器生成 multipart 边界）；spread 字面量拼接，零注解
const buildHeaders = (opt: DispatchOptions, method: string) => {
  const { params, idempotent = false, idemKey } = opt;
  const isForm = params instanceof FormData;
  const token = sessionStorage.getItem('reai_token') ?? '';
  return {
    ...(!isForm && !isQueryMethod(method) && params !== undefined
      ? { 'Content-Type': 'application/json' }
      : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(idempotent ? { 'Idempotency-Key': idemKey ?? crypto.randomUUID() } : {}),
  };
};

// 响应解析：401/1002 走中央回跳后抛出；其余业务码原样返回信封，由接口函数判断
const readEnvelope = async (res: Response, authRedirect: boolean) => {
  if (res.status === 401) {
    let msg = '未登录或登录已过期';
    try {
      const body = await res.json();
      msg = body?.msg || msg;
    } catch {
      msg = '未登录或登录已过期';
    }
    if (authRedirect) {
      handle401();
    }
    throw fail(msg, 1002);
  }
  const json = await res.json();
  if (json.code === 1002) {
    if (authRedirect) {
      handle401();
    }
    throw fail(json.msg || '未登录', json.code);
  }
  return json;
};

export const dispatch = async (opt: DispatchOptions) => {
  const method = opt.method ?? 'GET';
  const { params, authRedirect = true } = opt;
  const isForm = params instanceof FormData;
  const jsonBody =
    !isQueryMethod(method) && params !== undefined && !isForm ? JSON.stringify(params) : undefined;
  let res: Response;
  try {
    res = await window.fetch(buildUrl(opt, method), {
      method,
      headers: buildHeaders(opt, method),
      body: isForm ? params : jsonBody,
    });
  } catch {
    throw fail('网络异常，请检查后端是否启动', 5000);
  }
  return readEnvelope(res, authRedirect);
};

// JSON 快捷入口：自动解包 {code,msg,data}，code!==0 按错误码转中文抛错（err.code 供 2001 拒答等分支判断）
export const request = async (opt: DispatchOptions) => {
  const res = await dispatch(opt);
  if (res.code !== 0) {
    throw fail(errorMessage(res.code, res.msg), res.code);
  }
  return res.data;
};
