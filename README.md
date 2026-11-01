# bitrix24-mcp

[![CI](https://github.com/Rip-07/bitrix24-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Rip-07/bitrix24-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](pyproject.toml)
[![PyPI](https://img.shields.io/pypi/v/bitrix24-mcp-server.svg)](https://pypi.org/project/bitrix24-mcp-server/)

[English](#english) · [Русский](#русский)

MCP server that lets AI agents (Claude, ChatGPT, Cursor, your own agents) work with a
**Bitrix24** portal: CRM deals, contacts, leads and tasks.

> Unofficial project, not affiliated with 1C-Bitrix.

---

## Русский

### Что умеет

| Инструмент | Что делает | Режим |
|---|---|---|
| `whoami` | от имени какого пользователя работает вебхук | чтение |
| `list_deal_stages` | стадии воронки (для фильтров и смены стадии) | чтение |
| `list_deals` | сделки с фильтрами по стадии, воронке, ответственному, названию | чтение |
| `get_deal` | все поля сделки | чтение |
| `search_contacts` | поиск контактов по телефону, email или имени | чтение |
| `get_contact` | карточка контакта | чтение |
| `list_leads` | лиды, в том числе по статусу | чтение |
| `list_tasks` | задачи по ответственному и статусу | чтение |
| `create_lead` | создать лид | запись |
| `create_deal` | создать сделку (по умолчанию в KZT) | запись |
| `move_deal_stage` | перевести сделку на другую стадию | запись |
| `add_deal_comment` | комментарий в таймлайн сделки | запись |
| `create_task` | создать задачу | запись |

**По умолчанию сервер только читает.** Инструменты записи появляются при
`BITRIX24_READ_ONLY=false`.

### Быстрый старт

**1. Создайте входящий вебхук в Bitrix24.** Разработчикам → Другое → Входящий вебхук.
Дайте только нужные права (`crm`, `task`, `user`). Скопируйте URL вида
`https://ваш-портал.bitrix24.kz/rest/1/xxxxxxxx/`. **Это секрет**: с ним можно
действовать в CRM от имени пользователя вебхука.

**2. Подключите к Claude Code:**

```sh
claude mcp add bitrix24 \
  -e BITRIX24_WEBHOOK_URL="https://ваш-портал.bitrix24.kz/rest/1/xxxxxxxx/" \
  -- uvx --from bitrix24-mcp-server bitrix24-mcp
```

**Или к Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bitrix24": {
      "command": "uvx",
      "args": ["--from", "bitrix24-mcp-server", "bitrix24-mcp"],
      "env": { "BITRIX24_WEBHOOK_URL": "https://ваш-портал.bitrix24.kz/rest/1/xxxxxxxx/" }
    }
  }
}
```

Без uv: `pip install bitrix24-mcp-server`, затем команда `bitrix24-mcp`.

**3. Спросите агента:** «покажи сделки на стадии "Переговоры"» или «найди контакт
по номеру +7 701 123 45 67».

### Docker (HTTP-режим для удалённых агентов)

```sh
cp .env.example .env   # заполните BITRIX24_WEBHOOK_URL и MCP_AUTH_TOKEN
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

MCP-эндпоинт: `http://127.0.0.1:8000/mcp`. Клиент должен передавать заголовок
`Authorization: Bearer <MCP_AUTH_TOKEN>`. Без токена HTTP-режим не запустится.
Наружу публикуйте только через обратный прокси с TLS.

### Настройки

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BITRIX24_WEBHOOK_URL` | — | URL входящего вебхука (обязательно) |
| `BITRIX24_READ_ONLY` | `true` | `false` включает инструменты записи |
| `BITRIX24_ALLOW_RAW_CALLS` | `false` | инструмент `call_method` для любого метода REST API |
| `MCP_TRANSPORT` | `stdio` | `stdio` или `http` |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8000` | адрес HTTP-сервера |
| `MCP_AUTH_TOKEN` | — | Bearer-токен, обязателен для `http` |
| `MCP_ALLOW_NO_AUTH` | `false` | `true` разрешает `http` без токена (только доверенная сеть) |
| `MCP_ALLOWED_HOSTS` | — | разрешённые заголовки Host (защита от DNS rebinding) |
| `LOG_LEVEL` | `INFO` | уровень логов (пишутся в stderr) |

### Безопасность

- Режим только чтения по умолчанию, запись включается явно.
- Токен вебхука маскируется в логах и сообщениях об ошибках.
- Имена методов проверяются, произвольные пути к API не принимаются.
- HTTP-режим требует Bearer-токен. Docker-образ работает от непривилегированного пользователя.
- Повторные запросы при лимите Bitrix24 (`QUERY_LIMIT_EXCEEDED`).

### Частые проблемы

- `CERTIFICATE_VERIFY_FAILED` на macOS с Python из python.org: выполните `/Applications/Python 3.x/Install Certificates.command` или задайте `SSL_CERT_FILE=/etc/ssl/cert.pem`.

### Разработка

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check .
```

### Планы

Компании, товары в сделках, звонки и чат-боты (`imbot`), события через исходящие
вебхуки, OAuth-приложение для Маркетплейса Bitrix24. Предложения и PR приветствуются:
см. [CONTRIBUTING.md](CONTRIBUTING.md), задачи с меткой
[good first issue](https://github.com/Rip-07/bitrix24-mcp/labels/good%20first%20issue)
и [Discussions](https://github.com/Rip-07/bitrix24-mcp/discussions).

---

## English

MCP server for **Bitrix24** CRM and tasks. **Read-only by default**; set
`BITRIX24_READ_ONLY=false` to enable write tools (create leads, deals and tasks,
move deal stages, add timeline comments).

**Quick start (Claude Code):**

```sh
claude mcp add bitrix24 \
  -e BITRIX24_WEBHOOK_URL="https://your-portal.bitrix24.com/rest/1/xxxxxxxx/" \
  -- uvx --from bitrix24-mcp-server bitrix24-mcp
```

Without uv: `pip install bitrix24-mcp-server`, then run `bitrix24-mcp`.

Create the webhook under *Developer resources → Other → Inbound webhook* with only the
scopes you need (`crm`, `task`, `user`). The URL is a secret.

**Docker / remote agents:** `docker compose up -d` serves Streamable HTTP at
`/mcp` and requires `Authorization: Bearer <MCP_AUTH_TOKEN>`. See the settings table
above for all environment variables.

**Safety:** webhook tokens are masked in logs and errors, method names are validated,
rate-limit errors are retried with backoff, the Docker image runs as a non-root user.

### Troubleshooting

- `CERTIFICATE_VERIFY_FAILED` on macOS with the python.org installer: run `/Applications/Python 3.x/Install Certificates.command` or set `SSL_CERT_FILE=/etc/ssl/cert.pem`.

**Contributing:** see [CONTRIBUTING.md](CONTRIBUTING.md); questions and use cases go to
[Discussions](https://github.com/Rip-07/bitrix24-mcp/discussions).

## License

MIT © Askhat Akhtanov
