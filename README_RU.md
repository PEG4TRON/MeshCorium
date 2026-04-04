# Meshcorium

## Назначение проекта

MeshCorium - Self-hosted MeshCore клиент с гибридной системой контактов

Проект даёт единый интерфейс для работы с MeshCore-нодой через companion-прошивку и ориентирован на локальный запуск на Linux-хосте рядом с нодой.

Основной текущий транспорт:

- `USB serial`

## Ключевые особенности

- Python backend c локальной web-панелью
- Vue frontend для основных экранов
- работа с каналами, сообщениями и direct-диалогами
- работа с контактами и локальной backend БД контактов
- уведомления, unread/mention/direct counters
- различные звуки уведомлений для разного типа событий
- карта, маршруты и route trace инструменты
- возможность добавить "Нескучные обои"
- удалённая настройка repeater/room server через companion session
- systemd-friendly launcher для локальной установки как сервиса

## Архитектура в двух словах

- `meshcorium_web.py` — backend, HTTP API, SSE, session orchestration, локальные SQLite БД
- `meshcorium_client.py` — клиентский transport/protocol слой для MeshCore companion
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

## Удаление systemd-сервиса

```bash
./meshcorium-launcher.sh --service-remove
```

## Полезные замечания

- Если `web/dist` уже присутствует, launcher может использовать готовую frontend-сборку как fallback.
- Текущий релизный профиль ориентирован на `USB`-подключение companion-ноды.
- Локальные данные приложения обычно живут в:
  - `data/`
  - `logs/`

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
