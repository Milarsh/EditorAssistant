# Развёртывание EditorAssistant (Ubuntu)

Инструкция для бэкенда ([EditorAssistant](https://github.com/Milarsh/EditorAssistant)) и фронтенда ([EditorAssistantFront](https://github.com/Milarsh/EditorAssistantFront)) на Ubuntu 22.04+.

## 1. Подготовка сервера
- Установите Docker и Compose plugin:
  ```bash
  sudo apt update
  sudo apt install -y ca-certificates curl git docker.io docker-compose-plugin
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"   # перелогиньтесь после этого
  ```
- Установите Node.js 18+ и Yarn (нужно для сборки/запуска фронтенда):
  ```bash
  curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
  sudo apt install -y nodejs
  npm install -g yarn
  ```

## 2. Клонирование репозиториев
```bash
mkdir service && cd service
git clone https://github.com/Milarsh/EditorAssistant
git clone https://github.com/Milarsh/EditorAssistantFront
```

## 3. Переменные окружения — бэкенд
```bash
cd service/EditorAssistant
cp .env.example .env
```
Заполните `.env` минимум:
- Данные БД PostgreSQL (создаётся прямо в контейнере) (`POSTGRES_*`).
- Telegram API (`API_ID`, `API_HASH`). Ключи берутся на https://my.telegram.org.
- VK API (`VK_TOKEN`). Возьмите сервисный ключ доступа приложения на https://id.vk.com/business/go.
- SMTP для отправки кодов (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_TLS`). Данные выдаёт ваш почтовый сервис.

## 4. Экранные сессии (`screen`)
Чтобы процессы не завершались при закрытии SSH, создайте две сессии `screen` и внутри них запускайте бэкенд и фронтенд:
```bash
# сессия для бэкенда
screen -S ea-backend

# отдельная сессия для фронтенда
screen -S ea-frontend

# вернуться к сессии при необходимости
screen -r ea-backend
screen -r ea-frontend
# выйти, не останавливая процесс: Ctrl+A, затем D
```

## 5. Запуск бэкенда (в сессии ea-backend)
```bash
cd ~/service/EditorAssistant
docker compose up --build
```
Бэкенд слушает порт `8000`

## 6. Переменные окружения — фронтенд
Используйте готовые env-файлы в [EditorAssistantFront](https://github.com/Milarsh/EditorAssistantFront) и при необходимости скопируйте/правьте нужный (для продакшена — `.env.production`). Обязательно задайте:
- `VITE_API_URL` — URL бэкенда, например `http://<host>:8000`.

## 7. Запуск фронтенда (в сессии ea-frontend)
```bash
cd ~/service/EditorAssistantFront
yarn install
# убедитесь, что используется .env.production
yarn build:prod
yarn serve --host 0.0.0.0 --port 5173
```
Фронтенд будет доступен на `http://<host>:5173`.
