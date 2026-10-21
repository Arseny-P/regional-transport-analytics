import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import boundaries from 'eslint-plugin-boundaries';
import { defineConfig, globalIgnores } from 'eslint/config';

const layers = ['app', 'pages', 'widgets', 'features', 'entities', 'shared'];
const publicApi = 'index.{ts,tsx,js,jsx}';

const layerPolicy = (layer, index) => ({
  from: { element: { type: layer } },
  allow: {
    to: [
      {
        element:
          layer === 'app'
            ? { type: layer }
            : { type: layer, captured: { slice: '{{ from.element.captured.slice }}' } },
      },
      ...(layer === 'shared' ? ['shared'] : layers.slice(index + 1)).map((lower) => ({
        element: { type: lower, fileInternalPath: publicApi },
      })),
    ],
  },
});

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
  },
  {
    files: ['src/**/*.{js,jsx,ts,tsx}'],
    plugins: { boundaries },
    settings: {
      'import/resolver': { typescript: { project: './tsconfig.app.json' } },
      'boundaries/elements': [
        { type: 'app', pattern: 'src/app' },
        ...layers.slice(1).map((layer) => ({
          type: layer,
          pattern: `src/${layer}/*`,
          capture: ['slice'],
        })),
      ],
    },
    rules: {
      'boundaries/dependencies': [
        'error',
        { default: 'disallow', policies: layers.map(layerPolicy) },
      ],
    },
  },
]);
