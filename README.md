<div align="center">

# 🌸 Yume-Anime

[![Python](https://img.shields.io/badge/Python-3.14-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.x-005571?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18.6-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Grafana](https://img.shields.io/badge/Grafana-Observability-F46800?style=for-the-badge&logo=grafana&logoColor=white)](https://grafana.com/)

**Современный аниме-каталог с русскоязычным интерфейсом, интеллектуальным поиском через Shikimori GraphQL API и полноценным production-grade стеком мониторинга (Prometheus + Grafana + Loki + Grafana Alloy).**

</div>

---

## 📌 О проекте

**Yume-Anime** — это веб-приложение для поиска и просмотра каталога аниме. Проект спроектирован по принципам микросервисной архитектуры в Docker, разделен на статический frontend, мощный бэкенд на FastAPI, реляционную базу данных PostgreSQL и изолированный контур наблюдаемости (Observability).

---

## 📌 НОВОВЕДЕНИЯ - ИНФОРМАЦИЯ ТОЛЬКО ДЛЯ РАЗРАБОТЧИКОВ - ПЕРЕПИСАТЬ К РЕЛИЗУ

Особенность проекта — комбинированный **Local-First + External-Sync** поиск: система мгновенно выдает результаты из локальной базы PostgreSQL, параллельно обращаясь к внешнему GraphQL API Shikimori для обогащения данных, скачивания постеров и синхронизации новых тайтлов.

Проект должен удовлетворять 4 требованиям:
1) Простой деплой - проект можно развернуть где угодно в течение 5 минут, используя пару комманд
Реализция - использование docker-compose, ansible и облачных дистрибутивов
2) Мониторинг - любая ошика должна быть обнаружена и исправлена
Реализция - современный стек grafan alloy, grafan loki, grafana + prometheus
3) CI\CD код сам тестируется и развертывается во время разроботки
Реализация - планируется
4) Несмотря на открытый код весь проект защищен и вероятность атаки мимнимзирована

Нововедения:
В postgress автоматически создается база данных с несколькими таблицами, описанных в файле init.db (хранится в db/init.db).
Создается админка для редактирования аниме недели
Сильно обновлен дизайн, добавлено читай в документации

Я изучил архив anime_site_von_Vmsk_Wivi-aezi_branch_2.zip (README.md, Word-документацию и исходный код) и зафиксировал актуальную архитектуру, которая в ряде деталей расходится с документацией:

Админка и «Аниме недели»: во фронтенде появилась страница nginx/data/kamisama.html, а в python/main.py — полноценное API для anime_of_the_week (GET /api/anime-of-the-week, /archive, POST/PATCH/DELETE /api/admin/anime-of-the-week, /api/admin/login, /logout) с авторизацией через подписанные itsdangerous cookie (admin_session) и проверкой заголовка X-Requested-With: admin-ui.

Несовпадение ограничений для tagline: в db/init.sql задано CHECK (char_length(tagline) BETWEEN 5 AND 30), а в python/main.py и Word-документации проверяется 15 <= len(tagline) <= 20.

Порт Adminer: в docker-compose.yml сервис adminer_sql проброшен как 127.0.0.1:8080:8080, тогда как README.md и Word-документация указывают порт 8051.

Что сделано (заготовка для README.md)
Админ-панель (nginx/data/admin.html): создан интерфейс в красно-тёмной теме для управления разделом «Аниме недели» без внешней сборки.

Авторизация и безопасность: реализован вход по паролю через POST /api/admin/login с HttpOnly, Secure, SameSite=Strict cookie (admin_session), CSRF-защита заголовком X-Requested-With: admin-ui и безопасный рендеринг DOM через textContent.

Управление слотами: добавлены таблица недель (GET /api/admin/anime-of-the-week), переключение публикации (PATCH), удаление слота с файлом (DELETE) и форма добавления с живым поиском по /api/search/local, автовыравниванием даты на понедельник и слоганом 5–40 символов.

Онлайн-редактор 16:9: встроенный canvas-кроппер автоматически открывается для любых изображений, не совпадающих со стандартами 16:9 Full HD, 2K или 4K, и экспортирует обрезанный арт в .webp.

Архив и история замен (db/init.sql, python/main.py): в anime_of_the_week добавлены поля is_archived, archived_at и частичные уникальные индексы (WHERE is_archived = FALSE); при перезаписи занятого слота старое аниме уходит в архив с сохранением уникального .webp файла, а во вкладке архива отображаются статусы «архив», «текущее» и «запланировано».

Сети и хранилища: nginx подключён к frontend_net и monitor_net; api — ко всем трём сетям (frontend_net, backend_net, monitor_net); postgre_sql и adminer_sql — только к backend_net; prometheus, grafana, alloy, loki — к monitor_net. При этом ./anime_photo примонтирован одновременно в nginx (/usr/share/nginx/html/anime_photo/) и в api (/code/app/anime_photo), а alloy читает логи всех контейнеров напрямую через /var/run/docker.sock.

Известные ошибки:
1) В архиве аниме недели в Админке нельзя ничего кликать в чем тогда смысл архива?

Внешний поиск: GET /api/search/sync при каждом вызове делает локальный поиск в PostgreSQL, затем запрос к [https://shikimori.io/api/graphql](https://shikimori.io/api/graphql), параллельно скачивает постеры через .part-файлы в images.py и сохраняет новые тайтлы в anime_list.

![alt text](Documentation/Yume-Anime_Architecture_Easy.svg)

---

![alt text](photo_to_gitlab/image.png)

---

## 🚀 Архитектурный стек

| Компонент | Технология | Назначение |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3 Grid, Vanilla JS | Адаптивный пользовательский интерфейс, SPA-роутинг |
| **Backend** | FastAPI (Python 3.14), `psycopg`, `httpx` | REST API, логика поиска, интеграция с Shikimori |
| **Database** | PostgreSQL 18.6 | Хранение метаданных аниме и путей к локальным постерам |
| **Admin UI** | Adminer | Удобное веб-управление базой данных |
| **Web Server** | Nginx | Раздача статики, Reverse Proxy для `/api/` |
| **Metrics** | Prometheus & FastAPI Instrumentator | Сбор и хранение метрик производительности (RPS, Latency) |
| **Logs** | Grafana Alloy & Loki | Безагентный сбор Docker-логов (Alloy) и их централизованное хранение (Loki) |
| **Dashboards**| Grafana | Визуализация метрик и логов в реальном времени |

---

## 🏗️ Структура репозитория

```text
├── anime_photo/                # Локальное хранилище постеров (разделено с Nginx и Backend)
├── db/
│   └── init.sql                # SQL-скрипт инициализации таблицы anime_list
├── DockerFiles/
│   └── Dockerfile_python_backend # Dockerfile для сборки FastAPI-сервиса
├── env_examples/               # Шаблоны конфигурационных файлов (.env)
├── monitoring/
│   ├── alloy-config.alloy      # Конфигурация Grafana Alloy (сбор логов из Docker)
│   ├── loki-config.yaml        # Конфигурация Loki (хранение логов 7 дней)
│   └── prometheus/
│       └── prometheus.yml      # Scrape-конфигурация Prometheus
├── nginx/
│   ├── data/                   # Frontend-файлы (HTML, CSS, ассеты, фоны)
│   └── nginx_configuration/    # Конфиги Nginx (default.conf)
├── python/
│   ├── main.py                 # Основное FastAPI-приложение и эндпоинты
│   ├── shikimori.py            # Асинхронный GraphQL-клиент Shikimori
│   └── images.py               # Модуль параллельной загрузки постеров (.part -> rename)
└── docker-compose.yml          # Главный манифест оркестрации контейнеров

```

## 🌐 Схема взаимодействия сетей

Проект изолирован в трех Docker bridge-сетях для максимальной безопасности:

1. **`frontend_net`**: Связывает Nginx и FastAPI Backend.
2. **`backend_net`**: Изолирует FastAPI Backend, PostgreSQL и Adminer.
3. **`monitor_net`**: Объединяет сервисы мониторинга (Prometheus, Grafana, Alloy, Loki).

---

## ⚙️ Быстрый старт и развертывание

### 1. Подготовка окружения

Перед запуском контейнеров необходимо создать папку `env` в корне проекта и скопировать туда файлы конфигурации из `env_examples/`:

```bash
mkdir -p env
cp env_examples/.env.api.example env/.env.api
cp env_examples/.env.db.example env/.env.db
cp env_examples/.env.grafana.example env/.env.grafana

> ⚠️ **Важно:** Убедитесь, что переменная `DB_PASSWORD` в `.env.api` совпадает с `POSTGRES_PASSWORD` в `.env.db`. В файле `.env.grafana` используйте стандартный формат `KEY=VALUE` без ведущих дефисов.

### 2. Запуск проекта

Соберите и запустите все сервисы в фоновом режиме:

```bash
docker compose up -d --build

```

---

## 📊 Доступные сервисы

После успешного запуска вам будут доступны следующие веб-интерфейсы:

* 🌐 **Веб-сайт (Yume-Anime):** [http://localhost](http://localhost)


* 🗄️ **Adminer (База данных):** [http://localhost:8051](http://localhost:8051) *(Сервер: `postgre_sql`)*


* 📈 **Grafana (Дашборды и логи):** [http://localhost:3000](http://localhost:3000) *(Логин/Пароль из `.env.grafana`)*


* 🔭 **Prometheus (Метрики):** [http://localhost:9090](http://localhost:9090)


* 🧩 **Grafana Alloy (Инспекция сборщика):** [http://localhost:12345](http://localhost:12345)



---

## 🔍 API-Контракты

* `GET /api/random` — Возвращает до 6 случайных аниме из локальной базы (`ORDER BY RANDOM()`).


* `GET /api/search/local?q=<query>` — Мгновенный локальный поиск по полям `name`, `russian`, `japanese` с использованием `ILIKE`.


* `GET /api/search/sync?q=<query>` — Синхронный поиск: локальный поиск $\rightarrow$ GraphQL-запрос к Shikimori $\rightarrow$ параллельное скачивание постеров $\rightarrow$ `UPSERT` в PostgreSQL $\rightarrow$ возврат общего результата.


* `GET /api/anime/{id}` — Получение детальной информации по внутреннему ID аниме.


* `GET /metrics` — Эндпоинт для сбора метрик Prometheus (инструментирован через `prometheus-fastapi-instrumentator`).



---

## 🛠️ Планы по развитию (Roadmap)

* [ ] Реализация полноценной страницы деталей тайтла (жанры, студии, статус, рейтинг).


* [ ] Переход на полноценный шаблон Cache-Aside с TTL для внешних запросов к Shikimori.


* [ ] Добавление пользовательских аккаунтов, системы избранного и истории просмотров.


* [ ] Интеграция онлайн-плеера и каталога источников видео.


* [ ] Полная автоматизация импорта JSON-дашбордов Grafana через механизм provisioning.

---

## 🔌 Порты и подключение

В текущей конфигурации наружу на все интерфейсы публикуется только порт веб-сервера **Nginx (`80:80`)**. Остальные сервисы привязаны к **`127.0.0.1`** на хосте, поэтому напрямую из внешней сети они недоступны.

### Таблица портов сервисов

| Сервис | Контейнер | Проброс портов | Доступ | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| **Nginx** | `nginx_anime_container`[cite: 9] | `80:80`[cite: 9] | Напрямую (`http://<IP_сервера>`) | Фронтенд, постеры и проксирование `/api/` |
| **Adminer** | `adminer_container`[cite: 9] | `127.0.0.1:8080:8080`[cite: 9] | Через SSH-туннель (`localhost:8051`)[cite: 9] | Веб-интерфейс управления PostgreSQL[cite: 7] |
| **Grafana** | `grafana`[cite: 9] | `127.0.0.1:3000:3000`[cite: 9] | Через SSH-туннель (`localhost:3000`)[cite: 9] | Дашборды метрик и логов[cite: 7] |
| **Prometheus** | `prometheus`[cite: 9] | `127.0.0.1:9090:9090`[cite: 9] | Через SSH-туннель (`localhost:9090`)[cite: 9] | Сбор и просмотр метрик[cite: 7] |
| **Grafana Alloy** | `alloy`[cite: 9] | `127.0.0.1:12345:12345`[cite: 9] | Через SSH-туннель (`localhost:12345`)[cite: 9] | Статус и отладка сборщика логов |
| **Loki** | `loki`[cite: 9] | `127.0.0.1:3100:3100`[cite: 9] | Через SSH-туннель (`localhost:3100`)[cite: 9] | API хранилища логов |
| **FastAPI (`api`)** | `api_backend_container`[cite: 9] | *Внутренний (`8000`)* | Только внутри Docker-сетей[cite: 7, 9] | Бэкенд-сервис и `/metrics`[cite: 7] |
| **PostgreSQL** | `postgre_sql_container`[cite: 9] | *Внутренний (`5432`)* | Только внутри `backend_net`[cite: 7, 9] | База данных `anime_list`[cite: 7] |

---

### 🔐 Подключение к закрытым сервисам через SSH-туннель

Чтобы открыть **Grafana**, **Adminer** или другие сервисы с локального компьютера (например, с Windows), пробросьте нужные порты через SSH:

```bash
# Подключение к Grafana (локально откроется по http://localhost:3000)
ssh -L 3000:localhost:3000 vmsk@<IP_сервера>

# Подключение сразу к Grafana и Adminer
ssh -L 3000:localhost:3000 -L 8051:localhost:8051 vmsk@<IP_сервера>

# Проброс всех основных портов мониторинга и БД сразу
ssh -L 3000:localhost:3000 -L 8051:localhost:8051 -L 9090:localhost:9090 -L 12345:localhost:12345 -L 3100:localhost:3100 vmsk@<IP_сервера>

```

## 📝 Лицензия

Проект распространяется под лицензией MIT. Подробности смотрите в файле `LICENSE`.

С любовью от **Vmsk_Wivi** 🌸
=======
