// ESLint flat config for the browser UI. app.js is a classic script, not a module.
import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['.venv/', 'data/'] },
  js.configs.recommended,
  {
    files: ['app/static/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: globals.browser,
    },
  },
];
