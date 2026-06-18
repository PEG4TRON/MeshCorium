# Changelog

## v0.8.1 — Mobile UX & Quality (2026-06-18)

### Map provider fallback
- Unified MapLibre provider selection and fallback behavior across all secondary maps: message route maps, repeater geo picker, and contact route editor now honor the saved `map_provider` setting just like the main Maps page.
- Extracted shared map provider constants, style builders, tile proxy rewriting, provider normalization, and raster fallback helpers into `web/src/lib/mapLibre.js`.
- Added a 6-second map style boot timeout and error-triggered fallback from OpenFreeMap / OFM Liberty to OSM Raster for secondary map sheets, matching the main Maps page behavior.
- Continued routing both OpenFreeMap and OSM raster tile requests through the local `/api/tiles/proxy` endpoint to avoid direct LAN/browser tile loading problems.

### Map settings and data filtering
- Added a persisted `map_max_distance_km` client setting with a default of 400 km and a supported range of 1–20000 km.
- Added desktop and mobile Maps UI controls for changing the maximum contact-rendering distance. Contacts outside the configured home-node radius are filtered from map display.

### Settings and update UX
- Added a manual update-check button next to the displayed version in Settings → About.
- Corrected the Settings/About fallback display version for this release.

### Docker and release packaging
- Added `.meshcorium_version` to the Docker runtime image so containerized `/api/update/check` reports the same `0.8.1` version as the normal launcher build.
- Updated Docker Compose image/release metadata to `0.8.1` / `0.8.1--map-fixes`.
- Added the previously omitted helper script `download_meshcore_node_svgs.py` to the Docker runtime copy list, keeping root Python files explicit in the Dockerfile.
- Kept the cleaned release tree rules from v0.8.0: runtime data, logs, caches, virtual environments, and node modules are excluded from release artifacts.

### Messages

#### Scroll-to-newest
- **Fixed broken scroll-to-bottom button** in conversations: clicking "scroll to newest" now jumps directly to the last message in the database, loading a fresh batch of 50 latest messages and marking all previous messages as read.
- Added `latest=true` query parameter to `list_channel_messages` and `list_contact_messages` — direct jump to the newest DB messages instead of iterative pagination.
- Rewrote `scrollToNewestMessage()` in `MessagesView.vue`: single API call replaces old messages instead of merging, marks all messages up to the newest as read via `POST /api/messages/read-up-to`.
- Fixed infinite loop in `scrollToNewestMessage`: added `lastNewerLoadHadResults` ref guard in `canLoadNewerMessages` computed.
- Fixed missing `/api` prefix and wrong endpoint (`/messages/list` → `/api/messages/channel` with GET query params) in scroll-to-newest.
- Fixed `read-up-to` call: proper `POST` with `method` + `body: JSON.stringify(...)` and `conversation_kind`/`conversation_value` params.

#### Ghost channels (empty channel_identity)
- Backend: `_build_channel_unread_payload_for_port` now filters out messages with empty `channel_identity` from unread summary and logs a warning.
- Frontend: `regularNotificationEntries` in `ConnectedShellLayout.vue` skips channels with empty `channel_identity` (no more #N + 🔒 entries).
- Fixed `conn.fetchall()` on `sqlite3.Connection` (must be called on cursor, not connection).

### Mobile UI

#### Composer
- Send button moved to the right side of the input row, symmetric to the GIF button on the left — 46×46px icon-only button with paper-plane icon, no text label.
- `MessagesComposerBar.vue` imports `useIsMobile` for conditional rendering (icon on mobile, text label on desktop).

#### Icons
- All emoji icons (🔔💬👥🗺⚙) replaced with stroke-based SVG icons in the project's cyan-to-blue gradient style (#12B8F4→#5A74C9), viewBox 0 0 512 512.
- Five new icons created: `contacts-icon.svg`, `map-icon.svg`, `settings-icon.svg`, `disconnect-icon.svg`, `console-icon.svg` in `/icons/`.
- `MobileDockButton.vue` updated to support SVG URLs via `<img>` when icon starts with `/`.
- Emoji icons replaced in `ConnectedShellLayout.vue` (desktop rail + mobile dock), `MessagesView.vue` (mobile dock ×2), and `ContactsView.vue` (mobile dock).

#### Component extraction
- Extracted `MobileNodebar.vue` and `MobileDockBar.vue` from duplicative HTML in `MessagesView.vue` — eliminates copy-paste between conversation list and chat overlay views.
- Fixed vertical mobile dock regression: removed duplicate `<nav>` wrapper from `MobileDockBar.vue` (shell already provides the container).

#### Timestamp
- Added year to message timestamp format: `DD.MM, HH:MM` → `DD.MM.YYYY, HH:MM`.
- On mobile, message timestamp moved from message header to footer — separate line, right-aligned, 10px muted text.

### Frontend Engineering

#### CSS system
- All `100vh` replaced with `100dvh` (12 occurrences) for iOS Safari viewport stability.
- Unified border-radius into 4 CSS custom properties: `--mc-radius-sm: 8px`, `--mc-radius: 12px`, `--mc-radius-lg: 16px`, `--mc-radius-pill: 999px` — replaces 9 ad-hoc values (167 replacements).
- Added `:active` tactile button feedback: `scale(0.98) translateY(1px)`.
- Added `:focus-visible` a11y outlines: 2px accent border with 2px offset on all interactive elements.
- Added 200ms `transition` on `background-color`, `color`, `border-color`, `opacity`, `transform` for all interactive elements.
- Unified monospace font fallback: `"IBM Plex Mono", monospace` — removed `"Fira Code"`, `"Consolas"`, `"JetBrains Mono"` variants.
- Added skeleton loader CSS: `.mc-skeleton` with pulse animation, conversation and message bubble skeleton variants.
- Replaced 42 `.is-firefox` class selectors with `@supports (-moz-appearance: none)` feature queries.

#### Performance
- Added RAF debounce (`requestAnimationFrame` guard) for `updateConversationListMetrics()` in `useMessagesConversationList.js` — prevents double recalculation per frame from scroll + ResizeObserver events.

### Difference from v0.8.0
- v0.8.0 introduced the stable mobile UI and the initial Maps provider selector/fallback path on the main Maps page.
- v0.8.1 is a focused map-fixes release: it extends the same provider/fallback logic to every secondary MapLibre surface, adds a configurable contact distance limit, and fixes Docker/runtime version metadata for the new release.

---

## v0.8.1 — Mobile UX & Quality (2026-06-18) [RU]

### Fallback провайдера карт
- Унифицирован выбор MapLibre-провайдера и fallback-поведение во всех вторичных картах: карты маршрутов в сообщениях, выбор геопозиции repeater и редактор маршрута контакта теперь учитывают сохранённую настройку `map_provider`, как и основная страница Maps.
- Общие константы провайдеров, сборщики стилей, переписывание URL тайлов через proxy, нормализация провайдера и helpers растрового fallback вынесены в `web/src/lib/mapLibre.js`.
- Добавлен 6-секундный таймаут загрузки map style и fallback по ошибкам OpenFreeMap / OFM Liberty → OSM Raster для вторичных карт, в том же стиле, что и на главной странице Maps.
- Запросы тайлов OpenFreeMap и OSM raster продолжают идти через локальный `/api/tiles/proxy`, чтобы избежать проблем прямой загрузки тайлов из браузера в LAN-сценариях.

### Настройки карты и фильтрация данных
- Добавлена сохраняемая настройка клиента `map_max_distance_km`: по умолчанию 400 км, допустимый диапазон 1–20000 км.
- На desktop и mobile Maps добавлены элементы управления максимальной дистанцией отображения контактов. Контакты за пределами настроенного радиуса от home-ноды отфильтровываются с карты.

### Settings и проверка обновлений
- Добавлена кнопка ручной проверки обновлений рядом с версией в Settings → About.
- Исправлена fallback-версия, показываемая в Settings/About для этого релиза.

### Docker и релизная упаковка
- `.meshcorium_version` добавлен в runtime-образ Docker, поэтому контейнерный `/api/update/check` сообщает ту же версию `0.8.1`, что и обычный launcher-сценарий.
- Docker Compose metadata обновлены до `0.8.1` / `0.8.1--map-fixes`.
- В Dockerfile добавлен ранее пропущенный helper `download_meshcore_node_svgs.py`, чтобы root Python-файлы оставались явно перечислены.
- Сохранены правила чистого релизного дерева v0.8.0: пользовательские данные, логи, кэши, virtualenv и node_modules не входят в релизные артефакты.

### Сообщения

#### Прокрутка к новым
- **Исправлена сломанная кнопка прокрутки до конца** в диалогах: нажатие «к последнему» теперь переходит напрямую к последнему сообщению в базе данных, загружая свежую пачку из 50 последних сообщений и отмечая все предыдущие как прочитанные.
- Добавлен параметр `latest=true` в `list_channel_messages` и `list_contact_messages` — прямой переход к новейшим сообщениям в БД вместо итеративной пагинации.
- Переписан `scrollToNewestMessage()` в `MessagesView.vue`: один API-вызов заменяет старые сообщения вместо слияния, помечает все сообщения до новейшего как прочитанные через `POST /api/messages/read-up-to`.
- Исправлен бесконечный цикл в `scrollToNewestMessage`: добавлен guard `lastNewerLoadHadResults` ref в computed `canLoadNewerMessages`.
- Исправлен отсутствующий префикс `/api` и неверный endpoint (`/messages/list` → `/api/messages/channel` с GET query params) в scroll-to-newest.
- Исправлен вызов `read-up-to`: корректный `POST` с `method` + `body: JSON.stringify(...)` и параметрами `conversation_kind`/`conversation_value`.

#### Призрачные каналы (пустой channel_identity)
- Бэкенд: `_build_channel_unread_payload_for_port` теперь фильтрует сообщения с пустым `channel_identity` из unread-сводки и логирует предупреждение.
- Фронтенд: `regularNotificationEntries` в `ConnectedShellLayout.vue` пропускает каналы с пустым `channel_identity` (больше нет #N + 🔒 записей).
- Исправлен `conn.fetchall()` на `sqlite3.Connection` (должен вызываться на курсоре, а не на connection).

### Мобильный UI

#### Композер
- Кнопка отправки перемещена в правую часть строки ввода, симметрично кнопке GIF слева — иконка 46×46px с paper-plane, без текстовой метки.
- `MessagesComposerBar.vue` импортирует `useIsMobile` для условного рендеринга (иконка на mobile, текстовая метка на desktop).

#### Иконки
- Все emoji-иконки (🔔💬👥🗺⚙) заменены на stroke-based SVG иконки в градиентном стиле cyan-to-blue (#12B8F4→#5A74C9), viewBox 0 0 512 512.
- Создано пять новых иконок: `contacts-icon.svg`, `map-icon.svg`, `settings-icon.svg`, `disconnect-icon.svg`, `console-icon.svg` в `/icons/`.
- `MobileDockButton.vue` обновлён для поддержки SVG URL через `<img>`, когда иконка начинается с `/`.
- Emoji-иконки заменены в `ConnectedShellLayout.vue` (desktop rail + mobile dock), `MessagesView.vue` (mobile dock ×2) и `ContactsView.vue` (mobile dock).

#### Выделение компонентов
- Выделены `MobileNodebar.vue` и `MobileDockBar.vue` из дублирующего HTML в `MessagesView.vue` — устранён copy-paste между списком диалогов и оверлеем чата.
- Исправлена регрессия вертикального mobile dock: удалена дублирующая обёртка `<nav>` из `MobileDockBar.vue` (shell уже предоставляет контейнер).

#### Временные метки
- Добавлен год в формат временных меток сообщений: `DD.MM, HH:MM` → `DD.MM.YYYY, HH:MM`.
- На mobile временная метка перемещена из заголовка сообщения в футер — отдельная строка, выравнивание вправо, muted-текст 10px.

### Фронтенд-инженерия

#### CSS-система
- Все `100vh` заменены на `100dvh` (12 вхождений) для стабильности viewport в iOS Safari.
- Унифицирован border-radius в 4 CSS custom properties: `--mc-radius-sm: 8px`, `--mc-radius: 12px`, `--mc-radius-lg: 16px`, `--mc-radius-pill: 999px` — заменяет 9 ad-hoc значений (167 замен).
- Добавлена тактильная обратная связь `:active` для кнопок: `scale(0.98) translateY(1px)`.
- Добавлены a11y-обводки `:focus-visible`: акцентная рамка 2px с отступом 2px на всех интерактивных элементах.
- Добавлен 200ms `transition` для `background-color`, `color`, `border-color`, `opacity`, `transform` на всех интерактивных элементах.
- Унифицирован fallback моноширинного шрифта: `"IBM Plex Mono", monospace` — удалены варианты `"Fira Code"`, `"Consolas"`, `"JetBrains Mono"`.
- Добавлен CSS для skeleton loader: `.mc-skeleton` с pulse-анимацией, варианты скелета для диалогов и пузырей сообщений.
- 42 селектора `.is-firefox` заменены на feature-запросы `@supports (-moz-appearance: none)`.

#### Производительность
- Добавлен RAF debounce (`requestAnimationFrame` guard) для `updateConversationListMetrics()` в `useMessagesConversationList.js` — предотвращает двойной пересчёт за кадр от событий scroll + ResizeObserver.

### Отличия от v0.8.0
- v0.8.0 принёс стабильный mobile UI и начальный selector/fallback провайдера карт на основной странице Maps.
- v0.8.1 — точечный релиз исправлений карт: тот же provider/fallback распространён на все вторичные MapLibre-поверхности, добавлен настраиваемый лимит дистанции контактов, а Docker/runtime metadata версии исправлены для нового релиза.

## v0.8.0 — Mobile UI & Maps (stable) (2026-05-26)

### Mobile Responsive UI (1024px breakpoint)
- **Maps page**: Full-screen map with floating controls (☰ sidebar, 📍 center, ☀/🌙 theme), sidebar as bottom-sheet overlay (stats, legend, actions, route tracing), nodebar with ch/cont counters. Desktop unchanged.
- **Contacts page**: Full mobile shell with compact phonebar, topbar, collapsible search/filter tools, scrollable contacts body, mobile nodebar, bottom dock. Desktop unchanged.
- **Messages page**: Mobile shell with compact phonebar, topbar, messages list, composer, nodebar, bottom dock.
- **Settings navigation**: `/settings` shows only category list, section URLs show standalone page with mobile back action. Desktop unchanged.
- **Notifications overlay**: Notifications open as in-place shell overlay via `query.panel=notifications` instead of navigating to `/messages`. Preserves route query state.
- **Repeater management**: Adapted for mobile — full-screen category list + category content (9 categories), 2-level navigation like Settings. Added mobile repeater login form.
- **Mobile docks**: Contacts/Messages docks updated for shared shell-panel toggle. Added fallback global mobile dock for connected routes.
- **Mobile components**: `MobileContactsShell.vue`, `MobileDockButton.vue`, `MobileMessagesShell.vue`.

### Maps
- Added a persisted map provider selector on the desktop and mobile Maps sidebars, with the default OSM Raster provider and `OFM Liberty` saved through the MeshCorium client settings config file.
- Restored reliable map tile loading on the LAN stand by preventing double-proxy tile URLs, accepting valid empty vector `.pbf` tile responses in the backend proxy, and switching the main maps view to a fast OSM raster basemap through the local tile proxy when OpenFreeMap sprite/raster downloads stall.
- Fixed the OSM raster fallback tile template so MapLibre substitutes numeric `{z}/{x}/{y}` coordinates before the local proxy wraps the request.

### Fixes
- **Read marker on mobile back**: `goBackFromChat()` now calls `markVisibleMessagesRead()` before clearing conversation selection.
- **Channel unread summary key**: Fixed key mismatch in `setReadMarker` response handler — use `selectedChannelIdentity` when available.
- **Read tracking in loadNewerMessages**: Newly loaded messages at bottom of chat are immediately marked as read after merge.
- **Mobile Contacts notification badge**: Uses audible unread total instead of raw channel/contact unread maps.
- **Mobile Contacts nodebar**: Added `ch:` channel counter next to `cont:` contact counter.
- **SSE cascading disconnections**: Prevented cascading SSE disconnections when resuming background session from `_paused_background_session`. Added `_suppress_initial_connected_broadcast` flag.

### Service & Deployment
- Added systemd service unit (`meshcorium.service`) with automatic ttyACM0 permission fix.
- Service now handles all ttyACM* and ttyUSB* devices (nRF52, ESP32-S3, ESP32+CP2102/CH340).

### Architecture
- Refactored update check into `useUpdateCheck.js` composable.
- Unified mobile navigation patterns.
- Added `useIsMobile` composable (1024px breakpoint).
- Added `shellPanels.js` library for shared shell-panel state management.
- Added `contactRoutes.js` and `statusText.js` libraries.

### Frontend Changes
- `web/src/views/MapsView.vue`
- `web/src/views/MessagesView.vue`
- `web/src/views/ContactsView.vue`
- `web/src/views/SettingsView.vue`
- `web/src/components/layout/ConnectedShellLayout.vue`
- `web/src/components/layout/ShellPageFrame.vue`
- `web/src/components/layout/MobileContactsShell.vue` (new)
- `web/src/components/layout/MobileDockButton.vue` (new)
- `web/src/components/layout/MobileMessagesShell.vue` (new)
- `web/src/components/messages/MessagesMessageBubble.vue`
- `web/src/components/messages/MessagesMessageContextMenu.vue`
- `web/src/components/messages/MessagesNotificationsSheet.vue`
- `web/src/components/messages/MessagesRouteMapSheet.vue`
- `web/src/components/contacts/ContactsRepeaterGeoSheet.vue`
- `web/src/components/contacts/ContactsRouteEditorSheet.vue`
- `web/src/composables/useMessagesReadTracking.js`
- `web/src/composables/useUpdateCheck.js` (new)
- `web/src/composables/useIsMobile.js` (new)
- `web/src/lib/shellPanels.js` (new)
- `web/src/lib/contactRoutes.js` (new)
- `web/src/lib/statusText.js` (new)
- `web/src/i18n/messages/en.js`
- `web/src/i18n/messages/ru.js`
- `web/src/styles.css`
- `meshcorium_web.py`

### Test Server
- Deployed and running on test stand (192.168.2.22:8080)

---

## v0.7.0

Release `MeshCorium v0.7.0 -- Docker + USB + BLE + WIFI/LAN` promotes the previously experimental Wi-Fi/LAN TCP transport into the published release profile and aligns the runtime so post-connect behavior is transport-aware across USB, BLE, and Wi-Fi/LAN.

### Wi-Fi / LAN transport

- Wi-Fi/LAN TCP companion transport is now part of the release bundle through `meshcorium_wifi_transport.py` and `WIFI_TRANSPORT_TYPE` router integration.
- The connection UI now exposes a real manual `host:port` Wi-Fi/LAN connect flow instead of a placeholder-only transport tab.
- Saved/startup connection handling, phonebar transport state, and settings-side connection selection now understand Wi-Fi/LAN endpoints as first-class transport profiles.

### Runtime parity and message flow

- Active session routing for SSE, API requests, and post-connect screens was extended so Contacts, Messages, Maps, Settings, and shell runtime logic follow the actual active transport instead of assuming USB-only `selectedPort` semantics.
- Bootstrap now performs an initial queued-message drain after `ready` so message history does not wait for a later `MSG_WAITING` event before appearing.
- Wi-Fi frame read timeouts are now treated as transient idle gaps rather than fatal reader failures, reducing disconnects during long idle periods or heavy channel history reads.
- Conversation previews now stay aligned between the open chat and the dialog card list by applying fresh `/api/messages/conversations` preview data to live on-node dialog rows.

### Docker and packaging

- Docker release metadata now uses `v0.7.0` labels.
- The release Docker bundle continues to build the frontend inside Docker build and includes the current backend/frontend code used by the ordinary launcher runtime, including Wi-Fi/LAN transport support.
- Launcher-side frontend builds now reserve a larger default Node heap, reducing Vite out-of-memory failures on weaker hosts during release startup/build paths.

## v0.6.1

Release `MeshCorium v0.6.1 -- Docker + USB + BLE` is based on `v0.6.0` and keeps the same runtime variants while adding browser-side unread notifications and unread badge propagation into the tab title.

### Notifications and browser UX

- Browser notifications are now emitted for unread growth across all unread types after the current owner-scope and mute filters are applied.
- The browser tab title now receives a combined unread badge so MeshCorium remains visible even when the tab is in the background.
- Notification permission is requested from a real user gesture inside the shell so browser delivery works without breaking initial page load.

### Docker and runtime

- Docker release metadata now uses `v0.6.1` labels.
- The release Docker bundle continues to build the frontend inside Docker build and includes the current backend/frontend code used by the ordinary launcher runtime.

## v0.6.0

Release `MeshCorium v0.6.0 -- Docker + USB + BLE` promotes the post-`v0.5.3` development work into a release. The key difference from `v0.5.3 -- Docker + USB` is that BLE is now shipped as an available node connection path alongside the permanent USB serial transport, while Docker remains part of the ordinary release bundle.

### Connection and transports

- BLE connection to a MeshCore companion node is now available alongside the permanent USB serial transport.
- USB serial remains a first-class supported path and is not being removed.
- BLE support now includes discovery, node selection, PIN entry, connect flow, unpair action, pairing status, and separate BLE history in the connection UI.
- Backend transport handling was moved further toward the adapter model: USB serial and BLE are handled by transport-specific adapters while higher-level backend code uses universal connection/session calls.
- Known-node persistence was added for successful connections, transport type, BLE address, public key, node name, and saved BLE PIN state.
- BLE PIN handling was changed from repeated dynamic rotation to one-time managed initialization after the first successful user-provided PIN connection, with the saved PIN kept in the known-node DB.

### MeshCore node settings

- `/settings/node/meshcore-params` was expanded into dedicated MeshCore parameter pages.
- Radio settings now include regional presets, including a Russia preset, and safer backend application through the companion client instead of direct serial-only paths.
- BLE snapshot/apply operations now include pacing and short cooldowns to reduce the chance of overloading BLE-connected nodes during repeated heavy settings reads or writes.
- A separate battery settings page was added under `/settings/node/battery`.
- Battery profile settings allow per-node voltage range calibration for displayed battery percentage.

### Meshcorium data and owner-scope features

- Meshcorium settings now include separate controls for global contacts, messages, and channels across owner IDs.
- Global channel access can place channels from the local DB into free node IDX slots and remove the channels that were added by that mode when it is disabled.
- Channel metadata now tracks where channels exist on nodes and which IDX slots they occupy.
- Dialog/channel editing was extended with delete flows that remove channel IDX data from the node where applicable.
- Category-based DB import/export was added to `/settings/meshcorium`; imports merge with existing data, ignore exact duplicates, and surface conflicts where user choice is needed.

### Messages, notifications, and channels

- Message and unread handling was adjusted so owner-scope filtering affects counters, notification badges, and conversation visibility consistently.
- Mute / mentions-only behavior was corrected so ordinary unread badges and notification entries do not appear when a conversation is muted except for mentions.
- Channel list and conversation flows were updated around global-channel visibility and node IDX availability.

### UI and UX

- The connection float was redesigned around transport modes, with BLE-specific states and history separated from USB serial state.
- The phonebar is transport-aware: USB and BLE use different connection icons, while battery percentage is shown only for BLE/Wi-Fi style connections.
- Battery icons were added next to the phonebar battery percentage.
- Sync icons and active sync/scan animations were unified around `icons/sync.svg`.
- Dropdowns were improved with scroll handling and optional filtering when the menu does not fit on screen.
- Duplicate hover hints were removed where button text already explains the action.
- Route-level loading components were added for heavier Vue screens.
- Static visual assets such as background images are now cache-friendly for the browser.

### Battery history

- Battery readings are persisted per node owner ID.
- The battery page now includes a DB-backed graph with presets for 6 hours, 12 hours, 1 day, 1 week, 1 month, and custom ranges.
- The graph supports density control by averaging samples at lower density.
- Optional sunlight context can be shown under the graph when node geo is valid; all-zero coordinates are treated as missing geo.
- Battery history retention can be configured for 7 days, 1 month, 3 months, 6 months, or 1 year.

### Launcher and runtime

- Launcher venv handling was hardened so partial or missing virtual environments are recreated more reliably.
- Launcher can add the current user to serial-access groups detected from USB serial devices, such as `dialout`.
- Frontend build behavior remains compatible with a prebuilt `web/dist` fallback, while still rebuilding locally when Node/NPM are present.
- Docker was updated for the current runtime: the image now includes the new backend modules required by `meshcorium_web.py`, mounts host `/dev` and read-only `/run/udev` for launcher-like device visibility, and mounts host `/run/dbus` so BLE can use host BlueZ from inside the container.
- The Docker image tag and release label now use `v0.6.0` metadata instead of the old `v0.5.3-docker` label.

## v0.5.3

Release `v0.5.3 -- Docker + USB` is based on post-`v0.5.2` development work and adds the first official Docker packaging variant alongside the ordinary USB release workflow.

### Docker and runtime layout

- The release bundle now includes both:
  - the ordinary local launcher / systemd runtime
  - a Docker Compose runtime variant
- Added:
  - `Dockerfile`
  - `docker-compose.yml`
  - `docker/docker-entrypoint.sh`
  - `.dockerignore`
  - `defaults/client_settings.json`
- Docker runtime layout is now:
  - `/etc/meshcorium` for config
  - `/var/lib/meshcorium` for runtime data and SQLite DBs
  - `/var/log/meshcorium` for logs
- `meshcorium_web.py` now supports environment-driven runtime paths so the same backend can run in both local and containerized layouts without losing the ordinary `data/` + `logs/` defaults.

### Release notes
