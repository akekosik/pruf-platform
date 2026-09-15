# Журнал работ по прототипу ПРУФ

Файл нужен, чтобы контекст не терялся между сессиями. Каждая запись — что сделано, что дальше.

## Рабочие правила этой итерации

1. Песочница агента эфемерная и уже дважды сбрасывалась. Поэтому **источник истины — этот репозиторий**: каждый файл пишется сразу в `main`, локальный клон нужен только для прогона тестов и скриншотов.
2. Файлы пушатся по одному-двум за коммит. Большие файлы с кириллицей нельзя отправлять одним куском — обрывается содержимое (уже случилось с `web/index.html`, исправлено отдельным коммитом).
3. Прямой `git push` из песочницы невозможен (нет токена, `gh` не установлен) — только через GitHub API.

## Архитектура прототипа

- `engine/` — детерминированное ядро: `mutations` (18 операторов, AST-координаты), `sandbox` (изолированный прогон с лимитами CPU/AS/FSIZE), `analysis` (baseline + killed/survived + мутационный счёт), `session` (15 минут, вопросы из строк), `protocol` (контроль понимания, риски, цитаты, хронология), `economics`, `store`, `fixtures`, `cli`.
- `server/app.py` — HTTP-сервер на стандартной библиотеке, статика из `web/`, REST под `/api/*`.
- `web/` — фронтенд без сборки и без CDN: `css/app.css` (дизайн-система), `js/gl.js` (собственный WebGL-движок), `js/app.js` (API-клиент, подсветка кода, анимации), страницы `index`, `studio`, `session`, `employer`, `candidate`, `docs`.
- `docs/` — документация по образцу Stapel.

## Схемы API (сняты живыми запросами)

| Метод | Путь | Вход |
| --- | --- | --- |
| GET | `/api/health` | — |
| GET | `/api/tasks`, `/api/catalog`, `/api/economics`, `/api/vacancies`, `/api/candidates` | — |
| GET | `/api/demo?task=orders` | — |
| POST | `/api/mutations` | `{code, limit}` |
| POST | `/api/run` | `{code, tests}` |
| POST | `/api/analyze` | `{code, tests, limit}` |
| POST | `/api/session/start` | `{code, tests, meta, limit, questions}` |
| POST | `/api/session/{id}/answer` | `{question, option, seconds}` |
| POST | `/api/session/{id}/finish` | `{}` |
| GET | `/api/protocol/{id}[.txt\|.pdf]` | — |
| POST | `/api/protocol/{id}/send` | `{email, note}` |
| POST | `/api/leads` | `{name, email, company, plan, comment}` |

Эталонный прогон демо: задача `orders`, 27 строк, 16 мест правки, 12 мутаций, killed 7, survived 5, мутационный счёт 58 %, контроль понимания 70 %, отпечаток `392829790817d1b8`.

## Сделано

- [x] `web/css/app.css` — дизайн-система (тёмная палитра концепта, стекло, reveal-анимации, адаптив, `prefers-reduced-motion`).
- [x] `web/js/gl.js` — 3D-сцена на чистом WebGL: икосаэдр-каркас со светящимся ядром, торы, плавающие тела, параллакс по курсору, CSS-фолбэк при отсутствии WebGL.
- [x] `web/js/app.js` — API-клиент, подсветка Python, рендер кода с номерами строк, тосты, модалки, аккордеон, счётчики, gauge, localStorage-история сессий.
- [x] `web/index.html` — лендинг: hero с 3D, живой разбор мутаций, счётчики, четыре шага, интерактив «какая правка пройдёт незамеченной», три аудитории, протокол понимания, сравнение с конкурентами, «кто платит в первый год», тарифы, FAQ, рабочая форма заявки.

## Дальше по плану

- [ ] `web/js/landing.js` — оживление лендинга от `/api/demo` и `/api/economics`.
- [ ] `web/studio.html` + `js/studio.js` — редактор кода и тестов, прогон, мутации, полный анализ, запуск сессии.
- [ ] `web/session.html` + `js/session.js` — 15-минутная защита, таймер, вопросы, протокол, PDF.
- [ ] `web/employer.html`, `web/candidate.html` — кабинеты с реальными данными.
- [ ] `web/docs.html` — хаб документации с живым каталогом операторов и справочником API.
- [ ] `tests/` — автотесты ядра (`python3 -m unittest discover -s tests`).
- [ ] `scripts/make_reports.py`, `scripts/browser_checks.mjs` — воспроизводимые отчёты и браузерные проверки всех кнопок.
- [ ] `docs/documentation.md` — подробная документация по образцу Stapel.
- [ ] Обновить `CONTEXT.md`, `PLAN.md`, `README.md`.
