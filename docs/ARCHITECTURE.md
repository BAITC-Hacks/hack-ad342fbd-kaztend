# Архитектура

```mermaid
flowchart LR
  UI[frontend/index.html<br/>ванильный JS, SVG-картограмма, RU/KZ] -->|JSON| API[backend/app.py<br/>FastAPI]
  API --> ENG[engine.py<br/>детерминированный расчёт Score по ТЗ:<br/>валидатор, лаги, синергии, штрафы]
  API --> SEARCH[search.py<br/>кэш поиска по событию и приоритетам]
  AG --> CON[constraints.py<br/>бюджет, район, направления]
  API --> AN[analytics.py<br/>робастность весов (OECD/JRC), равенство,<br/>вклады Шепли, Парето-фронт]
  API --> EV[events.py<br/>шоки показателей до применения мер]
  API --> AG[agent.py<br/>LLM-агент с инструментами:<br/>catalog → validate → simulate → improve → best_under_budget]
  API --> AI[ai.py<br/>LLM-объяснение: structured outputs,<br/>DEMO_MODE fallback]
  API --> ST[store.py<br/>сценарии команд, data/scenarios.json]
  API --> RP[report.py<br/>Markdown-брифинг для акима]
  AG --> ENG
  AN --> ENG
  OPT[optimizer.py<br/>полный перебор 694 395 допустимых наборов] --> D1[(data/top_sets.json)]
  OPT --> D2[(data/pareto.json)]
  P[(data/passports.json<br/>ISO 37120, аналоги мер)] --> API
```

## Принципы
1. **Числа считает код, модель объясняет.** Все расчёты (Score, валидация, робастность, Парето) детерминированы и покрыты тестами; LLM получает готовые результаты и формулирует выводы. Агент выбирает меры только через инструменты симулятора.
2. **Работает без ключа.** `DEMO_MODE=true` или отсутствие `OPENAI_API_KEY` включает детерминированные объяснения и советника — жюри может проверить весь сценарий офлайн.
3. **Данные, а не код.** Районы, показатели, мероприятия, события и паспорта — данные (`engine.py`, `data/*.json`); модель расширяется на 6-й район Астаны (Сарайшык) и другие города без изменения логики.
4. **Каждая цифра проверяема.** Контрольные значения ТЗ (52.56, 56.5, 61 у.е.) зафиксированы в `backend/tests/test_engine.py`.

## Поток пользовательского сценария
Выбор 5 решений → живая валидация (`/api/validate`) → расчёт (`/api/simulate`) → карта и показатели районов → AI-объяснение (`/api/explain`) → аналитика (`/api/analyze`, `/api/pareto`) → агент-советник (`/api/agent`) → сохранение и сравнение (`/api/scenarios`) → брифинг (`/api/report`).
