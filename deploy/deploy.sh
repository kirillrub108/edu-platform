#!/usr/bin/env bash
# deploy/deploy.sh — деплой edllm на этом сервере.
# Запускается локально на сервере (руками для отладки) либо из GitHub Actions по SSH.
# Использование: deploy/deploy.sh <git_sha_short>
#
# Делает: build (sha-тег) -> [опционально pg_dump] -> migrate -> up --force-recreate
#         -> restart nginx -> локальный smoke-test -> retag :local + ретенция
#         либо, при провале smoke-теста: откат на last_good_sha без пересборки.

set -euo pipefail

# ---------- параметры ----------
SHA="${1:?usage: deploy.sh <git_sha_short>}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
STATE_DIR="${HOME}/.edllm-deploy"
STATE_FILE="${STATE_DIR}/last_good_sha"
KEEP_IMAGES=3
APP_SERVICES="backend celery_video celery_vision celery_quiz celery_email_worker flower"
SMOKE_URL_HEALTH="https://edllm.ru/health"
SMOKE_URL_DOCS="https://edllm.ru/docs"
SMOKE_RESOLVE="--resolve edllm.ru:443:127.0.0.1"
SMOKE_ATTEMPTS=12
SMOKE_SLEEP=10

mkdir -p "$STATE_DIR"

log() { echo "[deploy] $*"; }

# ---------- smoke-test (используется и для нового деплоя, и после отката) ----------
smoke_test() {
  local ok_health=false ok_docs=false
  for i in $(seq 1 "$SMOKE_ATTEMPTS"); do
    if [ "$ok_health" = false ] && curl -fsS $SMOKE_RESOLVE "$SMOKE_URL_HEALTH" >/dev/null; then
      log "/health OK"
      ok_health=true
    fi
    if [ "$ok_docs" = false ] && curl -fsS -o /dev/null $SMOKE_RESOLVE "$SMOKE_URL_DOCS"; then
      log "/docs OK"
      ok_docs=true
    fi
    if [ "$ok_health" = true ] && [ "$ok_docs" = true ]; then
      return 0
    fi
    log "smoke-test attempt $i/$SMOKE_ATTEMPTS: health=$ok_health docs=$ok_docs, retry in ${SMOKE_SLEEP}s"
    sleep "$SMOKE_SLEEP"
  done
  log "smoke-test FAILED: health=$ok_health docs=$ok_docs"
  return 1
}

# ---------- откат на предыдущий известный рабочий sha ----------
rollback() {
  local good_sha="$1"
  log "== ROLLBACK to $good_sha (no rebuild, images already local) =="
  BACKEND_IMAGE="edllm-backend:${good_sha}" FRONTEND_IMAGE="edllm-frontend:${good_sha}" \
    $COMPOSE up -d --force-recreate $APP_SERVICES frontend
  $COMPOSE restart nginx

  if smoke_test; then
    log "rollback OK, $good_sha is running again"
    exit 1   # деплой всё равно считается провалившимся — job должен быть красным
  else
    log "rollback ALSO FAILED — manual intervention required NOW"
    exit 2
  fi
}

# ---------- 1. сборка новых образов под sha ----------
log "== build backend + frontend ($SHA) =="
BACKEND_IMAGE="edllm-backend:${SHA}" $COMPOSE build backend
FRONTEND_IMAGE="edllm-frontend:${SHA}" $COMPOSE build frontend

# ---------- 2. проверка, есть ли новые миграции; если да — дамп БД ----------
log "== checking for pending migrations =="
CURRENT_REV="$(BACKEND_IMAGE="edllm-backend:${SHA}" $COMPOSE --profile migrate run --rm -T migrate \
  alembic current 2>/dev/null | tail -n1 | awk '{print $1}')"
HEAD_REV="$(BACKEND_IMAGE="edllm-backend:${SHA}" $COMPOSE --profile migrate run --rm -T migrate \
  alembic heads 2>/dev/null | tail -n1 | awk '{print $1}')"

log "current=$CURRENT_REV head=$HEAD_REV"

if [ "$CURRENT_REV" != "$HEAD_REV" ]; then
  log "== pending migration detected, dumping DB before upgrade =="
  DUMP_NAME="pre-migrate-${SHA}-$(date +%Y%m%d-%H%M%S).dump"
  # переиспользуем сервис db_backup: у него уже смонтирован volume db_backups
  # и заданы PGHOST/PGUSER/PGPASSWORD/PGDATABASE — просто подменяем entrypoint
  # с вечного цикла на разовый pg_dump
  $COMPOSE run --rm -T --entrypoint sh db_backup -c \
    "pg_dump -Fc -f /backups/${DUMP_NAME} && echo written:${DUMP_NAME}"
  log "backup saved: ${DUMP_NAME} (in db_backups volume)"

  log "== applying migrations =="
  BACKEND_IMAGE="edllm-backend:${SHA}" $COMPOSE --profile migrate run --rm migrate
else
  log "== no pending migrations, skipping dump + upgrade =="
fi

# ---------- 3. пересоздание контейнеров ----------
log "== recreate app containers =="
BACKEND_IMAGE="edllm-backend:${SHA}" FRONTEND_IMAGE="edllm-frontend:${SHA}" \
  $COMPOSE up -d --force-recreate $APP_SERVICES frontend

log "== restart nginx (upstream IP cache) =="
$COMPOSE restart nginx

# ---------- 4. smoke-test; провал -> откат ----------
if smoke_test; then
  log "== deploy OK, recording last_good_sha =="
  echo "$SHA" > "$STATE_FILE"

  # держим :local указывающим на актуальную версию для ручных docker compose up без переменных
  docker tag "edllm-backend:${SHA}" edllm-backend:local
  docker tag "edllm-frontend:${SHA}" edllm-frontend:local

  # ретенция: оставляем KEEP_IMAGES последних sha-тегов
  for img in edllm-backend edllm-frontend; do
    docker images "$img" --format '{{.Tag}}' \
      | grep -vE '^(local|<none>)$' \
      | sort -r \
      | tail -n +"$((KEEP_IMAGES + 1))" \
      | while read -r old_tag; do
          log "pruning old image ${img}:${old_tag}"
          docker rmi "${img}:${old_tag}" || true
        done
  done
  docker image prune -f

  log "== deploy finished successfully: $SHA =="
  exit 0
else
  if [ -f "$STATE_FILE" ]; then
    GOOD_SHA="$(cat "$STATE_FILE")"
    rollback "$GOOD_SHA"
  else
    log "smoke-test failed and no previous last_good_sha recorded — nothing to roll back to."
    log "manual intervention required."
    exit 2
  fi
fi
