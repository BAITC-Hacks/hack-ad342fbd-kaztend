#!/usr/bin/env bash
# Ежечасный чекпоинт для HackAlem AI (п. 5.4.8 и 5.9.2 Положения: у команды должен быть
# подтверждённый промежуточный результат по итогам КАЖДОГО часа соревновательной части).
# Использование:  ./checkpoint.sh h1 "core agent loop works end-to-end"
# Делает: git add -A, commit с меткой времени, тег hN, push веток и тегов.
set -euo pipefail
TAG="${1:?usage: ./checkpoint.sh <tag e.g. h1> <message>}"
MSG="${2:-checkpoint}"
STAMP="$(date '+%Y-%m-%d %H:%M')"
git add -A
if git diff --cached --quiet; then
  echo "Нет изменений для коммита — создаю пустой коммит-чекпоинт"
  git commit --allow-empty -m "checkpoint ${TAG} @ ${STAMP}: ${MSG}"
else
  git commit -m "checkpoint ${TAG} @ ${STAMP}: ${MSG}"
fi
git tag -f "${TAG}" -m "${MSG}"
git push origin HEAD
git push -f origin "${TAG}"
echo "OK: ${TAG} @ ${STAMP} запушен. Проверь на GitHub!"
