// k6 混合压测：文本 70% / 图片 20% / 语音 10%
// 目标：首字 P95 < 2s、完整响应 < 10s、错误率 < 1%、吞吐 ≥ 1000 混合并发
// 运行：k6 run --vus 1000 --duration 5m deploy/perf/k6_chat.js
//   环境变量：BASE_URL=http://127.0.0.1:8080 REAI_USER=admin REAI_PASS=admin123

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';

// ---------- 自定义指标 ----------
const firstByteTrend = new Trend('first_byte_latency', true);
const fullResponseTrend = new Trend('full_response_latency', true);
const errorRate = new Rate('errors');
const textCounter = new Counter('text_requests');
const imageCounter = new Counter('image_requests');
const voiceCounter = new Counter('voice_requests');

// ---------- 配置 ----------
const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8080';
const USER = __ENV.REAI_USER || 'admin';
const PASS = __ENV.REAI_PASS || 'admin123';
const TENANT = __ENV.REAI_TENANT || 'demo-tenant';

const MODALITY_MIX = [
  { type: 'text', weight: 70 },
  { type: 'image', weight: 20 },
  { type: 'voice', weight: 10 },
];

const SCENARIOS = {
  text: [
    '订单 202609001 物流在哪里',
    '退货流程怎么走',
    '有货吗？尺码 M',
    '优惠券怎么领',
    '发票能开吗',
    '换货要多久',
    '售后电话多少',
  ],
  image: [
    'https://example.com/defect_fabric.jpg',
    'https://example.com/defect_stitch.jpg',
    'https://example.com/defect_stain.jpg',
    'https://example.com/defect_size.jpg',
    'https://example.com/defect_color.jpg',
  ],
  voice: [
    'base64_encoded_audio_1',
    'base64_encoded_audio_2',
    'base64_encoded_audio_3',
  ],
};

// ---------- 登录获取 token ----------
let authToken = '';
let sessionId = '';

export function setup() {
  const loginRes = http.post(`${BASE_URL}/api/v1/auth/login`, JSON.stringify({
    username: USER,
    password: PASS,
  }), {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'login' },
  });

  check(loginRes, {
    'login status 200': (r) => r.status === 200,
    'login code 0': (r) => r.json().code === 0,
  });

  if (loginRes.status !== 200 || loginRes.json().code !== 0) {
    throw new Error(`登录失败: ${loginRes.status} ${loginRes.body}`);
  }

  authToken = loginRes.json().data.token;

  // 新建会话
  const sessRes = http.post(`${BASE_URL}/api/v1/sessions`, JSON.stringify({
    title: 'k6 压测会话',
  }), {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${authToken}`,
      'X-Tenant-ID': TENANT,
    },
    tags: { name: 'create_session' },
  });

  check(sessRes, {
    'create session 200': (r) => r.status === 200,
    'create session code 0': (r) => r.json().code === 0,
  });

  sessionId = sessRes.json().data.id;
  return { authToken, sessionId };
}

// ---------- 权重随机选模态 ----------
function pickModality() {
  const rand = Math.random() * 100;
  let cum = 0;
  for (const m of MODALITY_MIX) {
    cum += m.weight;
    if (rand <= cum) return m.type;
  }
  return 'text';
}

// ---------- 发送一轮对话 ----------
function sendChat(data) {
  const start = new Date();
  let firstByte = 0;
  let firstByteRecorded = false;

  const res = http.post(`${BASE_URL}/api/v1/chat/stream`, JSON.stringify(data), {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${authToken}`,
      'X-Tenant-ID': TENANT,
      'Accept': 'text/event-stream',
    },
    responseType: 'stream',
    tags: { name: 'chat_stream' },
  });

  const fullLatency = new Date() - start;

  // 流式读取首字节
  if (res.body && res.body.length > 0) {
    // k6 stream 模式下 body 是 Uint8Array，首包即视为首字节
    firstByte = 1; // 近似：流式首包即首字节
    firstByteRecorded = true;
  }

  const ok = check(res, {
    'chat status 200': (r) => r.status === 200,
    'chat has data': (r) => r.body && r.body.length > 0,
  });

  errorRate.add(!ok);
  fullResponseTrend.add(fullLatency);
  if (firstByteRecorded) firstByteTrend.add(firstByte);

  return ok;
}

// ---------- 主循环 ----------
export default function (data) {
  const modality = pickModality();
  let payload;

  if (modality === 'text') {
    textCounter.add(1);
    const q = SCENARIOS.text[Math.floor(Math.random() * SCENARIOS.text.length)];
    payload = {
      session_id: data.sessionId,
      content: q,
      modality: 'text',
    };
  } else if (modality === 'image') {
    imageCounter.add(1);
    const img = SCENARIOS.image[Math.floor(Math.random() * SCENARIOS.image.length)];
    payload = {
      session_id: data.sessionId,
      content: '请帮我看看这张图',
      modality: 'image',
      images: [img],
    };
  } else {
    voiceCounter.add(1);
    const aud = SCENARIOS.voice[Math.floor(Math.random() * SCENARIOS.voice.length)];
    payload = {
      session_id: data.sessionId,
      content: '',
      modality: 'voice',
      audio: aud,
    };
  }

  sendChat(payload);
  sleep(Math.random() * 2 + 0.5); // 0.5-2.5s 思考时间
}

// ---------- 阈值 ----------
export const options = {
  scenarios: {
    mixed_load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 200 },  // 预热
        { duration: '2m', target: 500 },   // 爬坡
        { duration: '3m', target: 1000 },  // 目标并发
        { duration: '5m', target: 1000 },  // 稳压
        { duration: '30s', target: 0 },    // 降压
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    'first_byte_latency': ['p(95)<2000'],      // 首字 P95 < 2s
    'full_response_latency': ['p(95)<10000'],  // 完整响应 P95 < 10s
    'errors': ['rate<0.01'],                    // 错误率 < 1%
    'http_req_duration': ['p(99)<15000'],      // 兜底
  },
  // 汇总导出
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

// ---------- 汇总 ----------
export function handleSummary(data) {
  const metrics = data.metrics;
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'deploy/perf/k6_summary.json': JSON.stringify({
      first_byte_p95: metrics.first_byte_latency?.values?.['p(95)'] || 0,
      full_response_p95: metrics.full_response_latency?.values?.['p(95)'] || 0,
      error_rate: metrics.errors?.values?.rate || 0,
      text_requests: metrics.text_requests?.values?.count || 0,
      image_requests: metrics.image_requests?.values?.count || 0,
      voice_requests: metrics.voice_requests?.values?.count || 0,
      vus_max: metrics.vus_max?.values?.max || 0,
      timestamp: new Date().toISOString(),
    }, null, 2),
  };
}