# Meshcorium

## Назначение проекта

MeshCorium - Self-hosted MeshCore клиент с гибридной системой контактов

Проект даёт единый интерфейс для работы с MeshCore-нодой через companion-прошивку и ориентирован на локальный запуск на Linux-хосте рядом с нодой.

Текущие транспорты:

- `USB serial`
- `BLE`
- `Wi-Fi / LAN`

Статус релиза `MeshCorium v0.8.1 -- map-fixes`:

- `USB serial` — постоянный и валидированный путь подключения, не удаляется из проекта
- `BLE` — дополнительный путь подключения к companion-ноде через Linux / BlueZ, рядом с USB serial
- `Wi-Fi / LAN` — ручной TCP `host:port` путь подключения, доступный рядом с USB serial и BLE
- `Docker Compose` — вариант эксплуатации остаётся рядом с обычным launcher/systemd сценарием; Docker metadata и runtime-версия выровнены на `0.8.1`

BLE вынесен в отдельный transport-адаптер и доступен в интерфейсе подключения. Это новый путь подключения, поэтому его поведение зависит от Linux-хоста, BlueZ и конкретного BLE-адаптера.

## Ключевые особенности

- Python backend c локальной web-панелью
- Vue frontend для основных экранов
- подключение к ноде через `USB serial`, `BLE` или `Wi-Fi / LAN`
- раздельная история подключений для USB и BLE-нод
- хранение известных нод и BLE PIN в локальной БД
- работа с каналами, сообщениями и direct-диалогами
- работа с контактами и локальной backend БД контактов
- уведомления, unread/mention/direct counters
- различные звуки уведомлений для разного типа событий
- карта, маршруты и route trace инструменты
- настройки параметров MeshCore-ноды, включая радио-пресеты
- отображение заряда ноды для BLE/Wi-Fi подключений и история батареи
- возможность добавить "Нескучные обои"
- удалённая настройка repeater/room server через companion session
- systemd-friendly launcher для локальной установки как сервиса

## Главное отличие `v0.8.1` от `v0.8.0`

`v0.8.1` — точечный релиз исправлений карт. Он сохраняет стабильный mobile UI и транспорты из `v0.8.0`, а дополнительно добавляет:

- общую MapLibre-логику выбора провайдера и fallback для всех вторичных карт, а не только для основной страницы Maps;
- fallback OpenFreeMap / OFM Liberty по таймауту загрузки и ошибкам на OSM Raster в картах маршрутов сообщений, выборе геопозиции repeater и редакторе маршрута контакта;
- сохраняемую настройку `map_max_distance_km`, управляющую максимальной дистанцией контактов, отображаемых на карте;
- кнопку ручной проверки обновлений в Settings -> About;
- исправленную Docker runtime-версию: `.meshcorium_version` копируется в образ, Compose metadata обновлены до `0.8.1`.

## Главное отличие `v0.7.0` от `v0.6.1`

В `v0.7.0` дополнительно добавлены:

- официальный релизный профиль `Wi-Fi / LAN` TCP transport с ручным `host:port` connect-flow;
- transport-aware post-connect routing, чтобы экраны и SSE-listeners следовали за активной сессией USB, BLE и Wi-Fi/LAN;
- обновлённые Docker release-label и image metadata для `v0.7.0`.

## Ключевые отличия `v0.6.x` / `v0.7.x` от `v0.5.3`

`v0.5.3` был релизом `Docker + USB`: Docker-вариант эксплуатации был добавлен к стабильному USB serial подключению, а BLE оставался в статусе задела.

В `v0.6.x` функционально добавлены и расширены:

- BLE-подключение к companion-ноде через Linux / BlueZ: поиск, выбор ноды, ввод PIN, подключение, unpair, отображение состояния pairing и отдельная история BLE-нод.
- Единая модель transport-адаптеров: backend работает через универсальные вызовы, а USB serial и BLE обрабатываются соответствующими адаптерами.
- БД известных нод: хранит успешные подключения, типы transport, BLE-адреса, public key и PIN, чтобы не держать историю только в конфиге браузера или `client_settings.json`.
- Настройки MeshCore-ноды: отдельные страницы параметров, радио-настройки, региональные пресеты и защитные паузы для BLE при тяжёлых запросах/применении параметров.
- Общий доступ к данным Meshcorium: отдельные тумблеры для контактов, сообщений и каналов разных ownerID без сброса ownerID текущей ноды.
- Карта IDX каналов на ноде: Meshcorium умеет поднимать каналы из локальной БД в свободные слоты ноды и очищать добавленные через общий доступ каналы при отключении режима.
- Импорт/экспорт БД по категориям в настройках Meshcorium с merge-поведением, обработкой дублей и предупреждениями по свободным IDX-слотам.
- UI/UX обновления: переработанный float подключения, отдельные состояния BLE, синхронизационные иконки/анимации, скроллируемые dropdown, route-level загрузчики, убранные дублирующие tooltip там, где текст уже есть на кнопке.
- Phonebar обновлён под transport-aware режим: USB и BLE имеют разные иконки, заряд показывается только для BLE/Wi-Fi, добавлены иконки батареи.
- Настройки батареи: профиль батареи ноды, пересчёт процента по напряжению, история заряда в БД, график с диапазонами, плотностью точек и опциональной полосой освещённости по геопозиции ноды.
- Launcher доработан для локального запуска: устойчивее создаёт venv, ставит зависимости и добавляет пользователя в группы доступа к USB serial устройствам.

## Архитектура в двух словах

- `meshcorium_web.py` — backend, HTTP API, SSE, session orchestration, локальные SQLite БД и универсальная orchestration-логика transport
- `meshcorium_client.py` — клиентский protocol слой для MeshCore companion
- `meshcorium_serial_transport.py` — USB serial transport-адаптер
- `meshcorium_ble_transport.py` — BLE transport-адаптер для Linux / BlueZ
- `known_nodes.py` — локальная БД известных нод и сохранённых BLE PIN
- `web/` — Vue frontend
- `meshcorium-launcher.sh` — bootstrap, установка зависимостей, запуск и systemd-install

## Что нужно для запуска

Launcher умеет сам дотягивать недостающие системные зависимости на Debian-подобных и RHEL-подобных системах, но запросит подтверждение у пользователя.

Типовой набор, который он ставит при необходимости:

- `python3`
- `python3-pip`
- `python3-venv` или `python3-virtualenv`
- `nodejs`
- `npm`

Дополнительно для установки как сервиса нужна systemd-система с `systemctl`.

## Быстрый запуск без установки сервиса

Из корня проекта:

```bash
./meshcorium-launcher.sh --run
```

Что произойдёт:

1. Launcher проверит системные зависимости.
2. Если чего-то не хватает, предложит установить это через системный пакетный менеджер.
3. Создаст `.venv`, если её ещё нет.
4. Установит Python-зависимости из `requirements.txt`.
5. Подготовит frontend-зависимости и сборку, если это нужно.
6. Запустит `meshcorium_web.py`.

По умолчанию web-интерфейс поднимается на:

- `http://0.0.0.0:8080`

## Установка как systemd-сервис

Из корня проекта:

```bash
./meshcorium-launcher.sh --install
```

Что произойдёт:

1. Launcher проверит и при необходимости установит системные зависимости.
2. Подготовит `.venv` и runtime/frontend зависимости.
3. Создаст unit:
   - `/etc/systemd/system/meshcorium.service`
4. Выполнит:
   - `systemctl daemon-reload`
   - `systemctl enable --now meshcorium.service`

## Вариант через Docker Compose

В этот релиз также входит Docker-вариант:

- `Dockerfile`
- `docker-compose.yml`

Он не заменяет обычный launcher или systemd-сценарий, а добавляется как ещё один способ эксплуатации той же сборки.

В `v0.8.1` Docker-вариант приведён к текущему коду приложения и релизной версии:

- образ собирает актуальный Vue frontend внутри Docker build
- backend включает новые модули известных нод, импорта/экспорта БД и BLE transport
- backend также включает модуль Wi-Fi/LAN TCP transport, используемый и обычным launcher runtime
- образ включает `.meshcorium_version`, поэтому Settings/About и `/api/update/check` внутри Docker показывают `0.8.1`
- USB serial остаётся доступен через проброс системного `/dev`
- BLE работает через host BlueZ: контейнер использует системный D-Bus socket хоста
- Wi-Fi/LAN TCP transport работает через обычную сеть контейнера и не требует отдельного device passthrough

Стандартные bind mounts в `docker-compose.yml`:

- `/etc/meshcorium` -> конфиг внутри контейнера `/etc/meshcorium`
- `/var/lib/meshcorium` -> runtime data внутри контейнера `/var/lib/meshcorium`
- `/var/log/meshcorium` -> логи внутри контейнера `/var/log/meshcorium`
- `/dev` -> системные устройства хоста внутри контейнера
- `/run/udev` -> read-only udev metadata для корректного обнаружения USB serial устройств
- `/run/dbus` -> host D-Bus socket для доступа к BlueZ при BLE-подключении

Compose запускает контейнер с `privileged: true`, чтобы Docker-вариант видел устройства так же, как обычный запуск лаунчером на хосте. Это нужно для динамических USB serial устройств (`/dev/ttyUSB*`, `/dev/ttyACM*`), Bluetooth/rfkill и других runtime device nodes, которые могут появиться уже после старта контейнера.

Типовой запуск:

```bash
docker compose up -d --build
```

Типовая остановка:

```bash
docker compose down
```

Замечания:

- контейнер собирается на базе `alpine:latest`
- Docker использует тот же backend/frontend код MeshCorium, что и обычный релиз
- BLE внутри Docker зависит от host `bluetoothd` / BlueZ и проброшенного `/run/dbus`
- если `/run/dbus/system_bus_socket` недоступен, контейнер стартует, но BLE будет недоступен
- USB serial остаётся независимым от BLE и продолжает работать через системные `/dev/tty*` устройства хоста
- из-за `privileged: true` Docker-вариант нужно запускать только на доверенном локальном хосте

## Обновление с `v0.5.0` / `v0.5.1`

Рекомендуемый порядок обновления:

1. Остановить текущий экземпляр MeshCorium.
   Если используется systemd:
   - `sudo systemctl stop meshcorium.service`

2. Сделать резервную копию пользовательских данных из старой установки:
   - `data/meshcorium_messages.sqlite3`
   - `data/meshcorium_contacts.sqlite3`
   - `data/client_settings.json`

3. Распаковать `MeshCorium v0.8.1 -- map-fixes` в новый каталог рядом со старой установкой.

4. Перенести сохранённые данные из старой `v0.5.0` установки в новый каталог:
   - скопировать нужные файлы в `data/`

5. Если старая установка работала как сервис, из нового каталога выполнить:

```bash
./meshcorium-launcher.sh --install
```

Это переиспользует новую версию launcher и обновит systemd unit на новый путь.

6. Если старая установка запускалась вручную, из нового каталога выполнить:

```bash
./meshcorium-launcher.sh --run
```

Замечания по обновлению:

- Если в `v0.5.0` у тебя встречалась ошибка
  - `expected CONTACTS_START, got code 18`
  то начиная с `v0.5.1` добавлена backend-защита от этого startup-сценария.
- Если в `v0.5.1` у тебя оставались общие connect/bootstrap timeout-сценарии, то в `v0.5.2` добавлены более глубокая backend-телеметрия старта и дополнительное укрепление transport/runtime-слоя.
- Старый каталог лучше оставить как резервную копию до подтверждения, что `v0.8.1` работает штатно.

## Удаление systemd-сервиса

```bash
./meshcorium-launcher.sh --service-remove
```

## Полезные замечания

- Если `web/dist` уже присутствует, launcher может использовать готовую frontend-сборку как fallback.
- Текущий релизный профиль поддерживает `USB serial`, `BLE`, `Wi-Fi / LAN` и Docker Compose вариант эксплуатации.
- Локальные данные приложения обычно живут в:
  - `data/`
  - `logs/`
- В Docker-варианте используются:
  - `/etc/meshcorium`
  - `/var/lib/meshcorium`
  - `/var/log/meshcorium`

#### Если проблемы с доступом к ноде **(нет прав)** проверь скрипт `grant-ttyacm0-perms.sh` Впиши в него своё устройство **`DEVICE_PATH`** (если отличается), и запусти.

## Основные режимы launcher

```bash
./meshcorium-launcher.sh --help
```

Ключевые флаги:

- `--run` — запуск без установки как сервиса
- `--install` — полная установка с systemd unit
- `--service-remove` — удаление systemd unit

## Changelog

- [CHANGELOG.md](./CHANGELOG.md)
