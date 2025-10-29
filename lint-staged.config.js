/**
 * @filename: lint-staged.config.js
 * @type {import('lint-staged').Configuration}
 */
export default {
  '*.{js,jsx,ts,tsx}': (stagedFiles) => [
    'yarn tsc -b',
    'eslint --fix .',
    `prettier --write ${stagedFiles.join(' ')}`,
  ],
  '*.css': (stagedFiles) => [`prettier --write ${stagedFiles.join(' ')}`],
}
