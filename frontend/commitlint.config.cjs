/**
 * commitlint：统一提交信息
 * 格式 <type>(<scope>): <subject>，subject 用 sentence-case 且 ≤100 字符。
 */
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'chore', 'revert', 'build', 'ci'],
    ],
    'subject-case': [2, 'always', ['sentence-case']],
    'header-max-length': [2, 'always', 100],
    'subject-empty': [2, 'never'],
    'type-empty': [2, 'never'],
  },
};
