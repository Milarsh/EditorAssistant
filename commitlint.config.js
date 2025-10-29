export default {
  extends: ['@commitlint/config-conventional'],
  ignores: [(commit) => commit.startsWith('initial')],
  rules: {
    'subject-empty': [2, 'never'],
    'type-empty': [2, 'never'],
  },
}
