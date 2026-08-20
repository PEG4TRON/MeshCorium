# Meshcorium Android Web Client

## English

Minimal Android client for `Meshcorium`:

- asks for the web interface URL on first launch
- opens the mobile web version inside a `WebView`
- registers an FCM token with the `Meshcorium` backend
- receives push notifications via Firebase Cloud Messaging

## What you need to build

1. Open the `android-web-client/` folder in Android Studio.
2. Add `app/google-services.json` from a Firebase Android project with package name `com.peg4tron.meshcorium`.
3. Make sure the `Meshcorium` server has the Firebase service account file at:
   `data/firebase_service_account.json`

You can override the path on the server via env:

```bash
MESHCORIUM_FCM_SERVICE_ACCOUNT_JSON=/abs/path/firebase_service_account.json python3 meshcorium_web.py
```

## How push notifications work

- The Android app receives an FCM registration token.
- The token is sent to the `Meshcorium` backend via `/api/mobile-push/register`.
- The backend stores registered devices in SQLite and sends FCM data-messages for new incoming messages.
- The app shows a local notification and opens the WebView at the saved URL.

## Limitations

- Without `google-services.json` the app will not build.
- Without `data/firebase_service_account.json` the backend will keep running, but push notifications will not be sent.
- Opening a notification currently returns the app to the base URL without precise navigation to a specific chat.

---

## Русский

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
