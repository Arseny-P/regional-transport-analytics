# Фронтенд

Веб-интерфейс сервиса анализа региональной транспортно-логистической системы. [Архитектура фронтенда](../docs/frontend-architecture.md).

## Локальный запуск

Используйте Node.js 22, как в CI. Выполните команды из каталога `frontend`.

```bash
npm ci
cp .env.example .env
npm run dev
```

Откройте <http://localhost:5173>. В `.env.example` включены моки API для запросов регионов и анализа. Для работы с Go API задайте `VITE_API_MOCKS=false` в `.env`. Vite проксирует запросы `/api/*` на `http://localhost:8080`.

Инструкции для запуска всех сервисов через Docker Compose есть в [корневом README](../README.md#локальный-запуск).

## Проверки и сборка

```bash
npm run check
npm run build
```

`npm run check` проверяет форматирование, запускает ESLint и проверяет типы TypeScript. `npm run build` создаёт production-сборку в `dist/`.

GitHub Actions выполняет `npm ci` и обе команды на Node.js 22. Workflow запускается для pull request и пушей в `main`, если изменились файлы в `frontend/` или сам workflow. Его также можно запустить вручную. При сборке CI задаёт `VITE_API_URL=/api` и `VITE_API_MOCKS=false`. [Конфигурация GitHub Actions](../.github/workflows/frontend.yml).
