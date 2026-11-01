# Changelog

## 0.1.0 — 2026-11-01

- First release.
- Read tools: `whoami`, `list_deal_stages`, `list_deals`, `get_deal`, `search_contacts`,
  `get_contact`, `list_leads`, `list_tasks`.
- Write tools (only with `BITRIX24_READ_ONLY=false`): `create_lead`, `create_deal`,
  `move_deal_stage`, `add_deal_comment`, `create_task`.
- Transports: stdio and Streamable HTTP with bearer-token auth.
- Pagination, rate-limit retries, webhook token masked in logs and errors.
