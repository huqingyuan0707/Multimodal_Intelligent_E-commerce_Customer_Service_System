// useSuggestedQuestions 单测（空态预设 6 条 + 关键词追问分支 + 默认兜底，对齐前端 Skill §8）
import { describe, expect, it } from 'vitest';
import { getFollowups, getWelcomeSuggestions } from './useSuggestedQuestions';

describe('useSuggestedQuestions', () => {
  it('空态预设返回 6 条真实问法', () => {
    const list = getWelcomeSuggestions();
    expect(list).toHaveLength(6);
    expect(list[0]).toBe('退货政策是什么');
  });

  it('退货回答给出换货/运费/到账三条延伸', () => {
    expect(getFollowups('支持 7 天无理由退货')).toEqual([
      '换货流程要几天？',
      '运费谁承担？',
      '退款多久到账？',
    ]);
  });

  it('瑕疵回答给出留证/转人工延伸', () => {
    expect(getFollowups('袖口脱线约 2cm')).toContain('需要拍几张照片留证？');
  });

  it('无命中走默认兜底三条', () => {
    expect(getFollowups('今天天气怎么样')).toEqual([
      '还能再详细说说吗？',
      '有相关的政策原文吗？',
      '帮我转人工确认一下',
    ]);
  });
});
