import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { FlatCompat } from '@eslint/eslintrc'
import js from '@eslint/js'
import pluginRouter from '@tanstack/eslint-plugin-router'
import typescriptEslint from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import react from 'eslint-plugin-react'
import simpleImportSort from 'eslint-plugin-simple-import-sort'
import storybookPlugin from 'eslint-plugin-storybook'
import unusedImports from 'eslint-plugin-unused-imports'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const compat = new FlatCompat({
  baseDirectory: __dirname,
  recommendedConfig: js.configs.recommended,
  allConfig: js.configs.all,
})

export default [
  {
    ignores: [
      '**/lint-staged.config.js',
      'dist',
      'src/**/icons',
      '.storybook/static',
    ],
  },
  ...compat.extends(
    'airbnb',
    'airbnb/hooks',
    'plugin:@typescript-eslint/recommended',
    'prettier',
    'plugin:react/recommended',
  ),
  ...pluginRouter.configs['flat/recommended'],
  ...storybookPlugin.configs['flat/recommended'],
  {
    plugins: {
      '@typescript-eslint': typescriptEslint,
      react,
      'unused-imports': unusedImports,
      'simple-import-sort': simpleImportSort,
    },

    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2018,
      sourceType: 'module',

      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },

        tsconfigRootDir: __dirname,
      },
    },

    rules: {
      'react-hooks/exhaustive-deps': 2,
      'react/require-default-props': 'off',
      'import/no-unresolved': 0,
      'no-use-before-define': 'off',

      '@typescript-eslint/no-use-before-define': [
        'error',
        {
          functions: true,
          classes: true,
          variables: false,
        },
      ],

      'import/extensions': [
        2,
        {
          png: 'always',
          jpg: 'always',
          json: 'always',
          svg: 'always',
          webp: 'always',
          mp3: 'always',
          mov: 'always',
          webm: 'always',
          avif: 'always',
        },
      ],

      'simple-import-sort/imports': 'error',
      'simple-import-sort/exports': 'error',

      'react/prop-types': 0,
      'no-shadow': 'off',
      '@typescript-eslint/no-shadow': ['error'],
      'react/jsx-uses-vars': 1,
      'jsx-a11y/anchor-is-valid': 'off',

      'react/jsx-filename-extension': [
        2,
        {
          extensions: ['.js', '.jsx', '.ts', '.tsx'],
        },
      ],

      'arrow-body-style': 'off',
      'react/jsx-props-no-spreading': 'off',

      'max-len': [
        'error',
        {
          code: 120,
          ignoreUrls: true,
          ignoreTrailingComments: true,
          ignoreRegExpLiterals: true,
          ignorePattern: '^import .*',
        },
      ],

      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      'unused-imports/no-unused-imports': 'error',

      'unused-imports/no-unused-vars': [
        'warn',
        {
          vars: 'all',
          varsIgnorePattern: '^_',
          args: 'after-used',
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],

      'react/no-unescaped-entities': 'off',
      'react/jsx-one-expression-per-line': 'off',
      'object-curly-newline': 'off',

      'react/style-prop-object': [
        2,
        {
          allow: ['StatusBar'],
        },
      ],

      'global-require': 'off',
      camelcase: 'off',
      'no-underscore-dangle': 'off',
      '@typescript-eslint/ban-ts-comment': 'off',
      'import/prefer-default-export': 'off',
      'lines-between-class-members': 'off',
      'no-plusplus': 'off',
      'react/jsx-uses-react': 'off',
      'react/react-in-jsx-scope': 'off',
      '@typescript-eslint/no-explicit-any': 'off',

      'padding-line-between-statements': [
        'error',
        {
          blankLine: 'always',
          prev: '*',
          next: 'return',
        },
        {
          blankLine: 'always',
          prev: ['const', 'let', 'var'],
          next: '*',
        },
        {
          blankLine: 'any',
          prev: ['const', 'let', 'var'],
          next: ['const', 'let', 'var'],
        },
      ],

      'func-names': 'off',
      'import/no-extraneous-dependencies': 'off',
      '@typescript-eslint/no-duplicate-enum-values': 'off',
      'no-console': 2,

      curly: [2, 'all'],

      'react/function-component-definition': [
        2,
        {
          namedComponents: 'arrow-function',
        },
      ],

      'react/no-unstable-nested-components': 'off',
    },
  },
]
