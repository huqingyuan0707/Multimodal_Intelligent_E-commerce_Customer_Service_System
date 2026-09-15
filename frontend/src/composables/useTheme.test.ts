// useTheme 单测（默认浅色 / 切换落类与持久化 / initTheme 读偏好防闪白，对齐 DESIGN.md §Colors）
// node 环境无 DOM：用最小 document/localStorage 桩（storage 键 reai.theme 与 tokens 的 .dark 联动口径）。
// 注意：vi.resetModules() 会连 stubGlobal 一起还原，故每用例 import 前必须重新打桩。
import { beforeEach, describe, expect, it, vi } from 'vitest';

const store: Record<string, string> = {};
const classes = new Set<string>();

// 桩 document 会让 vue runtime-dom 的模块级探测走 DOM 分支，故补齐 createElement 系列
const fakeEl = () => ({ style: {}, setAttribute: () => {}, appendChild: () => {} });

const installStubs = () => {
  vi.stubGlobal('document', {
    documentElement: {
      classList: {
        toggle: (name: string, on: boolean) => {
          if (on) {
            classes.add(name);
          } else {
            classes.delete(name);
          }
        },
      },
    },
    createElement: fakeEl,
    createElementNS: fakeEl,
    createTextNode: fakeEl,
    createComment: fakeEl,
    querySelector: () => null,
  });
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
  });
};

// 被测模块持模块级单例 ref，须每用例前重置模块态（resetModules 后重新打桩）
const fresh = async () => {
  vi.resetModules();
  installStubs();
  return import('./useTheme');
};

beforeEach(() => {
  delete store['reai.theme'];
  classes.clear();
});

describe('useTheme', () => {
  it('无存储偏好时 initTheme 落浅色（html 不挂 .dark）', async () => {
    const { initTheme, theme } = await fresh();
    initTheme();
    expect(theme.value).toBe('light');
    expect(classes.has('dark')).toBe(false);
  });

  it('toggleTheme 切深色：写 localStorage 且挂 .dark，再切回则还原', async () => {
    const { initTheme, theme, toggleTheme } = await fresh();
    initTheme();
    toggleTheme();
    expect(theme.value).toBe('dark');
    expect(store['reai.theme']).toBe('dark');
    expect(classes.has('dark')).toBe(true);
    toggleTheme();
    expect(theme.value).toBe('light');
    expect(classes.has('dark')).toBe(false);
  });

  it('深色偏好持久化：initTheme 读到 dark 即首帧挂 .dark（防闪白）', async () => {
    store['reai.theme'] = 'dark';
    const { initTheme, theme } = await fresh();
    initTheme();
    expect(theme.value).toBe('dark');
    expect(classes.has('dark')).toBe(true);
  });
});
