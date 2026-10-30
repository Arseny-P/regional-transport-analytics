# Архитектура frontend

## 1. Структура приложения

Миграция на FSD и TypeScript завершена: в `src/` нет `.js`/`.jsx` файлов, `allowJs` выключен.

```
src/
  app/
    main.tsx            точка входа: стили, иконки Leaflet, MSW в dev, рендер App
    App.tsx             роутер: /start, /analysis, /result внутри AppLayout
    leafletIcons.ts     фикс путей к иконкам маркеров Leaflet
    styles/index.css    глобальные стили
    mocks/              MSW-моки /analysis* для dev-режима
  pages/
    start/              стартовый экран
    analysis/           выбор области и видов транспорта, запуск анализа
    result/             статус задачи, граф на карте, выбор метрики
  widgets/
    app-layout/         header, sidebar (портал AppSidebar), footer
    map-view/           карта Leaflet с тайлами OSM
  features/
    select-area/        выбор прямоугольной области кликами или координатами
    run-analysis/       создание задачи POST /analysis
    select-metric/      выбор графовой метрики
  entities/
    area/               BBox и функции работы с ним
    transport-mode/     виды транспорта road | rail | sea и подписи
    analysis/           типы задачи и графа, heartbeat, получение результата, слой графа
  shared/
    api/                HTTP-клиент, ApiError, общие типы
    config/             API_URL, настройки карты, регион по умолчанию
    ui/                 переиспользуемые UI-элементы (Button)
```

## 2. Слои FSD

```
src/
  app/        инициализация: App, роутер, провайдеры, глобальные стили
  pages/      страницы, одна папка на маршрут
  widgets/    крупные самостоятельные блоки UI
  features/   пользовательские действия, которые несут бизнес-ценность
  entities/   бизнес-сущности
  shared/     общий переиспользуемый код
```

### Правила

1. **Импорт только вниз.** Модуль слоя может импортировать только из слоёв ниже:
   `app → pages → widgets → features → entities → shared`.
   Slice одного слоя не импортирует другой slice того же слоя.
2. **Public API.** Каждый slice (`features/select-area`, `entities/area`, …) экспортирует наружу только то, что указано в его `index.ts`. В `shared` у каждого сегмента свой `index.ts` (`shared/config`, `shared/api`, …).
   Импорт внутренних файлов чужого slice запрещён: `@/entities/area/lib/bbox` нельзя, `@/entities/area` можно.
3. **Alias `@/`** указывает на `src/`. Между slice импортируем через alias, внутри slice относительными путями.
4. **Сегменты** внутри slice: `ui` (компоненты), `model` (типы, состояние, бизнес-логика), `api` (запросы), `lib` (вспомогательные функции), `config` (константы).
5. **Нейминг.** Slice в kebab-case (`select-area`), компоненты в PascalCase (`SelectArea.tsx`), только именованные экспорты.
6. **Код пишется только на TypeScript** (`.ts`/`.tsx`).

## 3. Где что размещать

| Что                                            | Куда                                            | Пример                                          |
| ---------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- |
| Страница маршрута                              | `pages/<name>/ui/<Name>Page.tsx`                | `pages/analysis`                                |
| Общая оболочка, крупный блок                   | `widgets/<name>`                                | `widgets/map-view`, `widgets/app-layout`        |
| Действие пользователя                          | `features/<verb-noun>`                          | `features/select-area`, `features/run-analysis` |
| Бизнес-сущность, её типы и функции             | `entities/<name>/model`, `entities/<name>/lib`  | `entities/area` (`BBox`, `bboxFromPoints`)      |
| Запросы к backend по сущности                  | `entities/<name>/api` или `features/<name>/api` | `features/run-analysis/api/createAnalysis.ts`   |
| HTTP-клиент, базовый URL                       | `shared/api`, `shared/config`                   | `shared/api/client.ts`                          |
| Константы и настройки                          | `shared/config`                                 | `DEFAULT_MAP_CENTER`, `OSM_TILE_URL`            |
| Переиспользуемые UI-элементы (кнопка, спиннер) | `shared/ui`                                     | `shared/ui/button`                              |
| Общие типы без бизнес-смысла                   | `shared/lib`, `shared/types`                    | —                                               |
| Глобальные стили, провайдеры, роутер           | `app/`                                          | `app/styles/index.css`                          |

Типы хранятся рядом с кодом, которому они принадлежат: тип сущности в `entities/<name>/model/types.ts`, тип ответа API в сегменте `api` того slice, который делает запрос.

## 4. Сценарий анализа

1. `/analysis`: пользователь выделяет область и виды транспорта, `features/run-analysis` отправляет `POST /analysis` с `job_id`, сгенерированным на frontend.
2. После создания задачи происходит переход на `/result?job_id=...`. Параметры хранятся в URL, поэтому перезагрузка страницы их не теряет.
3. `/result`: `entities/analysis` шлёт heartbeat по `job_id`, при готовности получает граф и метрики, граф рисуется на карте, метрика выбирается через `features/select-metric`.

### Моки API

Пока Go API не готов, в dev-режиме запросы `/analysis*` перехватывает MSW (`src/app/mocks`). Моки включаются переменной `VITE_API_MOCKS=true` в `.env`.
