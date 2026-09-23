# AGENTS.md — контекст для AI-агентов (Codex / Claude)

Проект: «Аким на 5 часов» — AI-симулятор бюджета Астаны (HackAlem AI, спец-трек Astana Innovations).
Задача: пользователь распределяет бюджет 100 у.е. между 5 решениями, получает Astana Quality of Life Score, объяснение и советы.

## Правила
- Формула Score и правила валидации — из ТЗ, менять нельзя; контрольные числа зафиксированы в `backend/tests/test_engine.py` (52.56 / 56.5 / 61).
- Числа считает код (`engine.py`, `analytics.py`), LLM только объясняет и выбирает через инструменты (`ai.py`, `agent.py`).
- Всё должно работать без ключа (`DEMO_MODE=true` или пустой `OPENAI_API_KEY`).
- Секреты только в `.env`; в репозиторий — только `.env.example`.
- Интерфейс RU/KZ, ванильный JS без сборки; внешние ресурсы не подгружать (жюри может быть офлайн).
- Команда работает на Windows: скрипты в двух версиях (`scripts/*.ps1` и `*.sh`).

## Команды
```
pip install -r requirements.txt
python -m pytest -q backend/tests
python -m uvicorn backend.app:app --port 8000
```
