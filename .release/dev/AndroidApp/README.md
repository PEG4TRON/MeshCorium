# Meshcorium Android Web Client

Минимальный Android-клиент для `Meshcorium`:

- при первом запуске спрашивает URL веб-интерфейса
- открывает мобильную web-версию внутри `WebView`
- регистрирует FCM-токен в `Meshcorium` backend
- принимает push-уведомления через Firebase Cloud Messaging

## Что нужно для сборки

1. Открыть папку `android-web-client/` в Android Studio.
2. Добавить `app/google-services.json` от Firebase-проекта Android-приложения с package name `com.peg4tron.meshcorium`.
3. Убедиться, что на сервере `Meshcorium` лежит сервисный аккаунт Firebase:
   `data/firebase_service_account.json`

Можно переопределить путь на сервере через env:

```bash
MESHCORIUM_FCM_SERVICE_ACCOUNT_JSON=/abs/path/firebase_service_account.json python3 meshcorium_web.py
```

## Как работает push

- Android-приложение получает FCM registration token.
- Токен отправляется на backend `Meshcorium` через `/api/mobile-push/register`.
- Backend хранит зарегистрированные устройства в SQLite и при новых входящих сообщениях отправляет FCM data-message.
- Приложение показывает локальное уведомление и открывает WebView по сохраненному URL.

## Ограничения

- Без `google-services.json` приложение не соберется.
- Без `data/firebase_service_account.json` backend продолжит работать, но push не будет отправляться.
- Открытие уведомления пока возвращает в приложение на базовый URL без точечной навигации к конкретному чату.
