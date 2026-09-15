#!/usr/bin/env bash
# ПРУФ · восстановление рабочего окружения после сброса песочницы.
#
#   git clone --depth 1 https://github.com/akekosik/pruf-platform.git /data/repo \
#     && bash /data/repo/tools/restore.sh
#
# Делает: клон (если нужно) → правки 0.9.1 и 0.9.2 → автотесты → сервер на фоне → /api/health.
# Аргументы: $1 — каталог репозитория (/data/repo), $2 — порт (8777).
set -u

REPO="${1:-/data/repo}"
PORT="${2:-8777}"
URL="https://github.com/akekosik/pruf-platform.git"

if [ ! -d "$REPO/.git" ]; then
  echo "── клонирую $URL → $REPO"
  rm -rf "$REPO"
  git clone --depth 1 "$URL" "$REPO" || exit 1
fi

cd "$REPO" || exit 1

echo "── правки 0.9.1"
python3 tools/apply_fixes.py
echo "── правки 0.9.2"
python3 tools/apply_fixes_2.py

echo "── автотесты"
python3 -m unittest discover -s tests 2>&1 | tail -3

if curl -s -m 2 "http://127.0.0.1:$PORT/api/health" > /dev/null 2>&1; then
  echo "── сервер уже работает на порту $PORT"
else
  echo "── поднимаю сервер на порту $PORT"
  nohup python3 -m engine.cli serve --port "$PORT" > /data/server.log 2>&1 &
  echo $! > /data/server.pid
  sleep 2
fi

python3 - <<PY
import json, urllib.request
try:
    data = json.load(urllib.request.urlopen("http://127.0.0.1:$PORT/api/health", timeout=5))
    print("── /api/health:", json.dumps(data, ensure_ascii=False))
except Exception as error:
    print("── /api/health не ответил:", error)
PY

echo "── готово. Дальше: python3 tools/qa_api.py --base http://127.0.0.1:$PORT"
echo "                node tools/qa_browser.js --base http://127.0.0.1:$PORT --out /data/qa"
