/**
 * 新会话预设问题 + 回答后追问延伸（职责：空态引导与猜你想问）
 * 链路：ChatView 空态欢迎卡 / 最后一条 Agent 回复下追问 chips → 点击直接发送
 * 对齐：页面设计.md §3.1 状态空（新会话引导卡）+ design.pen 对话助手-预设/追问画板
 */
import type { Reference } from '@/types/agent';

// 空态预设：一键发送的真实业务问法（售前/售中/售后/多模态全覆盖）
export const WELCOME_SUGGESTIONS = [
  '退货政策是什么',
  '这件破洞能换货吗',
  '现在下单多久发货',
  '这件有 L 码吗？帮我推荐尺码',
  '有什么优惠券可以用',
  '我的订单到哪了',
] as const;

// 关键词命中即给 3 条延伸追问（规则前置，后端就绪 followups 字段后可整体替换为服务端下发）
const FOLLOWUP_RULES = [
  { keys: ['退货', '退换'], items: ['换货流程要几天？', '运费谁承担？', '退款多久到账？'] },
  {
    keys: ['换货', '破洞', '瑕疵', '脱线', '勾丝'],
    items: ['帮我提交换货申请', '需要拍几张照片留证？', '可以转人工确认一下吗？'],
  },
  {
    keys: ['发货', '物流', '订单', '到哪', '快递'],
    items: ['帮我查一下物流到哪了', '可以改收货地址吗？', '发货超时有补偿吗？'],
  },
  {
    keys: ['尺码', '推荐', 'L 码', 'M 码', '版型'],
    items: ['偏大还是偏小？按平时码买吗？', '支持换码吗？运费谁出？', '帮我查 L 码有货吗？'],
  },
  {
    keys: ['优惠', '券', '满减', '包邮'],
    items: ['券和满减能叠加吗？', '券的有效期到哪天？', '满多少包邮？'],
  },
  {
    keys: ['退款', '到账', '审批'],
    items: ['退款原路返回吗？', '退款审批要多久？', '帮我催一下退款进度'],
  },
] as const;

const DEFAULT_FOLLOWUPS = ['还能再详细说说吗？', '有相关的政策原文吗？', '帮我转人工确认一下'] as const;

// 空态预设问题（欢迎卡 chips 用）
export const getWelcomeSuggestions = () => [...WELCOME_SUGGESTIONS];

// 按回答内容 + 引用标题匹配追问（瑕疵/引用优先，命中即返回 3 条，否则默认兜底）
export const getFollowups = (content: string, references?: Reference[]) => {
  const hay = `${content} ${(references ?? []).map(r => r.title).join(' ')}`;
  const hit = FOLLOWUP_RULES.find(r => r.keys.some(k => hay.includes(k)));
  return hit ? [...hit.items] : [...DEFAULT_FOLLOWUPS];
};

// 新会话预设 + 追问延伸统一出口（页面只从这里拿 chips，不散写文案）
export const useSuggestedQuestions = () => ({ getWelcomeSuggestions, getFollowups });
