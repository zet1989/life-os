#!/bin/bash
curl -sv -X POST https://zyryanov-n8n.ru/api/watch/push \
  -H "Authorization: Bearer wk_0881039935c24045b4fa7e392bd441da" \
  -H "Content-Type: application/json" \
  -d '{"heart_rate":72,"steps":5000}'
