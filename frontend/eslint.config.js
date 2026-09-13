import js from '@eslint/js';
import pluginVue from 'eslint-plugin-vue';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';
import globals from 'globals';

/**
 * ESLint 扁平配置（ESLint 9）
 *
 * 硬约束（提交即拦截，对应 skill frontend-code-style）：
 *  - func-style: expression  → 页面方法一律箭头函数，禁止 function 声明
 *  - no-explicit-any: warn   → 不阻断 CI，但既有 any 不扩散（配合 --max-warnings 0 时按需放宽）
 */
export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'coverage/**',
      'node_modules/**',
      'auto-imports.d.ts',
      'components.d.ts',
      '*.config.js',
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],

  {
    files: ['**/*.{ts,tsx,vue}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      // —— 页面方法一律箭头函数（本项目强制，见 skill / 测试评估验收方案 第 3 节）——
      'func-style': ['error', 'expression', { allowArrowFunctions: true }],
      'prefer-arrow-callback': 'error',

      // —— 类型 ——
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],

      // —— 通用 ——
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'prefer-const': 'error',
      eqeqeq: ['error', 'always', { null: 'ignore' }],

      // —— 防屎山量化门禁（对应 skill anti-shit-code §2，存量已验证为 0 违规）——
      'max-depth': ['error', 3], // 嵌套 ≤3 层
      'max-lines': ['error', { max: 400, skipBlankLines: true, skipComments: true }], // 单文件 ≤400 行
      complexity: ['error', 20], // api/index.ts request() 信封解包收口处为 18，阈值取 20
      'max-params': ['error', 4], // 参数 >4 考虑封装对象

      // —— Vue ——
      'vue/multi-word-component-names': 'off',
      'vue/define-macros-order': ['error', { order: ['defineProps', 'defineEmits'] }],
      'vue/component-api-style': ['error', ['script-setup']],
      'vue/block-order': ['error', { order: ['template', 'script', 'style'] }],
      // 页面直接写 fetch/axios 会被拦（必须先落到 src/api/index.ts）
      'no-restricted-globals': [
        'error',
        { name: 'fetch', message: '禁止在页面直接使用 fetch，请走 src/api/index.ts' },
      ],
    },
  },

  {
    files: ['src/api/**/*.ts', '**/*.test.ts', '**/*.spec.ts', 'vite.config.ts'],
    rules: {
      'no-restricted-globals': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },

  {
    files: ['**/*.cjs'],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },

  prettier,
);
