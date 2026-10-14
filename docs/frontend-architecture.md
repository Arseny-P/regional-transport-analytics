# Архитектура frontend

## 1. Текущее состояние

### Структура до миграции

```
src/
  main.jsx            точка входа, глобальные стили, фикс иконок Leaflet
  App.jsx             роутер и общий Layout
  leafletIcons.js     фикс путей к иконкам маркеров Leaflet
  index.css
  layout/Layout.jsx   header, выезжающий sidebar, footer
  components/MapView.jsx   карта и выбор прямоугольной области
  pages/AnalysisPage.jsx   ввод области и режима, запрос /analyze
  pages/ResultPage.jsx     iframe с картой результата, запрос /metrics
```

## 2. Целевая структура (FSD)

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
6. **Новый код пишется на TypeScript** (`.ts`/`.tsx`). JS-файлы допустимы только как ещё не мигрированные.

## 3. Где что размещать

| Что | Куда | Пример |
|---|---|---|
| Страница маршрута | `pages/<name>/ui/<Name>Page.tsx` | `pages/analysis` |
| Общая оболочка, крупный блок | `widgets/<name>` | `widgets/map-view`, `widgets/app-layout` |
| Действие пользователя | `features/<verb-noun>` | `features/select-area`, `features/run-analysis` |
| Бизнес-сущность, её типы и функции | `entities/<name>/model`, `entities/<name>/lib` | `entities/area` (`BBox`, `bboxFromPoints`) |
| Запросы к backend по сущности | `entities/<name>/api` или `features/<name>/api` | `features/run-analysis/api/analyze.ts` |
| HTTP-клиент, базовый URL | `shared/api`, `shared/config` | `shared/api/client.ts` |
| Константы и настройки | `shared/config` | `DEFAULT_MAP_CENTER`, `OSM_TILE_URL` |
| Переиспользуемые UI-элементы (кнопка, спиннер) | `shared/ui` | `shared/ui/spinner` |
| Общие типы без бизнес-смысла | `shared/lib`, `shared/types` | — |
| Глобальные стили, провайдеры, роутер | `app/` | `app/styles/index.css` |

Типы хранятся рядом с кодом, которому они принадлежат: тип сущности в `entities/<name>/model/types.ts`, тип ответа API в сегменте `api` того slice, который делает запрос.

## 4. План дальнейшей миграции

1. **`shared/api` + `shared/config/env`.** Вынести базовый URL backend в `VITE_API_URL` (`.env`, `.env.example`). Сделать типизированный клиент и описать типы ответов `/analyze`, `/map`, `/metrics`;
2. **`entities/transport-mode`.** Тип `TransportMode = "auto" | "aero" | "sea" | "rail" | "all"` и подписи режимов (сейчас дублируются в двух страницах);
3. **`widgets/app-layout`.** Перенести `layout/Layout.jsx`, убрав двойное оборачивание (см. ниже);
4. **`shared/ui`.** Спиннер, кнопки и оверлей загрузки вместо повторяющихся inline-стилей;
5. **`features/run-analysis`, `pages/analysis`.** Запрос анализа и форма координат и режима;
6. **`features/select-metric`, `pages/result`**;
7. **`app/`.** Перенести `App`, роутер, `index.css`, `leafletIcons`,`main.jsx` → `main.tsx`;
8. **Выключить `allowJs`**, когда JS-файлов не останется. Удалить неиспользуемый `leaflet-draw`.

## 5. Найденные проблемы (исправить в ходе миграции)

- **Двойной Layout.** `App.jsx` оборачивает маршруты в `Layout`, и каждая страница тоже рендерит свой `Layout`. В итоге header, кнопка меню и footer рендерятся дважды
- **Мёртвые условия** `mode === "all1"` / `mode !== "all1"` в `ResultPage.jsx`: значения `all1` не существует, ветка «метрики недоступны» никогда не показывается
- **Дублирование** `@keyframes spin` в двух страницах, много inline-стилей, `marginTop: "450px"` для позиционирования кнопки
- **Обработка ошибок через `alert`**, состояние области передаётся между страницами через `location.state` и теряется при перезагрузке `/result`. Исправляется использованием `react router`
- В footer ссылка ведёт на исходный репозиторий `agalikeev/analyze-logistic`.
