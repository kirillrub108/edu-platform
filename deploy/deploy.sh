#!/usr/bin/env bash
# deploy/deploy.sh — zero-downtime deploy of edllm on this server.
# Runs locally on the server (by hand for debugging) or from GitHub Actions over SSH.
#
#   deploy/deploy.sh <git_sha_short>     full deploy
#   deploy/deploy.sh --switch blue|green flip the live slot by hand (no build)
#   deploy/deploy.sh --init-state [slot]  write the generated files, touch nothing else
#   deploy/deploy.sh --self-test         exercise slot resolution, touches nothing
#
# The web tier runs as two slots (backend_blue/backend_green, frontend_blue/
# frontend_green). A release boots the IDLE slot, waits for it to be healthy,
# repoints nginx at it with a reload, smoke-tests through nginx, and only then
# stops the old slot. Users keep their connections through the switch; nginx
# reload lets established requests finish on the old worker processes.
#
#   build → migration guard → [dump] → migrate → up target slot → wait healthy
#   → switch upstream → smoke → retag :local → recreate workers → stop old slot
#   → record state → prune
#
# Failure BEFORE the switch: the target containers are removed, production never
# noticed. Failure AFTER the switch: the upstream goes back to the old slot,
# which is still running. Either way the job exits non-zero. Rollback onto
# last_good_sha remains the path for late failures, when the old slot is gone.
#
# Destructive migrations (drop/rename/NOT NULL) cannot be deployed live — both
# releases share the database during the switch. app.scripts.migration_guard
# stops the deploy before the migration runs; DEPLOY_ALLOW_UNSAFE_MIGRATION=1
# re-runs it behind the maintenance page instead. See docs/DECISIONS.md §53.

set -euo pipefail

# shellcheck source=deploy/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

# ---------- параметры ----------
KEEP_IMAGES=3
# Restarted (not blue-green'd) after the web switch: a warm SIGTERM lets the
# current task finish inside stop_grace_period, and acks_late re-queues whatever
# did not. See docs/DECISIONS.md §53.
WORKER_SERVICES="celery_video celery_vision celery_quiz celery_email_worker flower"
SMOKE_URL_HEALTH="https://edllm.ru/health"
SMOKE_URL_DOCS="https://edllm.ru/docs"
SMOKE_RESOLVE="--resolve edllm.ru:443:127.0.0.1"
SMOKE_ATTEMPTS=12
SMOKE_SLEEP=10
# Readiness of a freshly started slot. 60 × 3s comfortably covers the backend's
# 30s start_period plus gunicorn boot.
READY_ATTEMPTS=60
READY_SLEEP=3

# ---------- self-test: pure slot logic, no docker, no side effects ----------
self_test() {
  local tmp failures=0
  tmp="$(mktemp -d)"
  # shellcheck disable=SC2317  # invoked via trap
  trap 'rm -rf "$tmp"' RETURN

  EDLLM_STATE_DIR="${tmp}/state"
  EDLLM_UPSTREAM_FILE="${tmp}/active.conf"
  EDLLM_PROM_TARGETS_FILE="${tmp}/backend.json"
  STATE_DIR="$EDLLM_STATE_DIR"
  SLOT_FILE="${STATE_DIR}/active_slot"
  UPSTREAM_FILE="$EDLLM_UPSTREAM_FILE"
  PROM_TARGETS_FILE="$EDLLM_PROM_TARGETS_FILE"

  check() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
      echo "  ok    ${label}: ${actual}"
    else
      echo "  FAIL  ${label}: expected '${expected}', got '${actual}'"
      failures=$((failures + 1))
    fi
  }

  echo "== deploy.sh --self-test =="

  check "no state at all defaults to blue" "blue" "$(resolve_active_slot)"

  mkdir -p "$STATE_DIR"
  printf 'garbage\n' > "$SLOT_FILE"
  check "corrupt state file defaults to blue" "blue" "$(resolve_active_slot)"

  printf 'green\n' > "$SLOT_FILE"
  check "state file is used when no include exists" "green" "$(resolve_active_slot)"

  render_upstream blue
  check "include wins over the state file" "blue" "$(resolve_active_slot)"
  check "include parses back" "blue" "$(upstream_slot)"

  render_upstream green
  check "include re-render flips the slot" "green" "$(resolve_active_slot)"

  printf 'not an upstream file\n' > "$UPSTREAM_FILE"
  check "unparsable include falls back to state" "green" "$(resolve_active_slot)"

  check "other_slot blue" "green" "$(other_slot blue)"
  check "other_slot green" "blue" "$(other_slot green)"

  record_active_slot blue
  check "record_active_slot round-trips" "blue" "$(recorded_slot)"

  # Rendering must be idempotent apart from the generated timestamp comment.
  local first second
  render_upstream blue
  first="$(grep -v '^# ACTIVE WEB SLOT' "$UPSTREAM_FILE")"
  render_upstream blue
  second="$(grep -v '^# ACTIVE WEB SLOT' "$UPSTREAM_FILE")"
  if [ "$first" = "$second" ]; then
    check "render_upstream is idempotent" "same" "same"
  else
    check "render_upstream is idempotent" "same" "differs"
  fi

  # The generated files are git-ignored: a fresh clone, or the pull that landed
  # the commit untracking them, leaves them absent. They must come back from the
  # recorded slot — never invented.
  rm -f "$UPSTREAM_FILE" "$PROM_TARGETS_FILE"
  record_active_slot green
  ensure_generated_state > /dev/null
  check "missing include is regenerated from state" "green" "$(upstream_slot)"
  if grep -q '"backend_green:8000"' "$PROM_TARGETS_FILE" 2>/dev/null; then
    check "missing prometheus targets are regenerated" "green" "green"
  else
    check "missing prometheus targets are regenerated" "green" "missing/wrong"
  fi

  # Present files must be left exactly as they are.
  render_upstream blue
  record_active_slot green
  ensure_generated_state > /dev/null
  check "existing include is NOT overwritten by state" "blue" "$(upstream_slot)"

  if [ "$failures" -eq 0 ]; then
    echo "== self-test OK =="
    return 0
  fi
  echo "== self-test FAILED (${failures}) =="
  return 1
}

# ---------- slot helpers ----------
slot_containers() {
  local slot="$1"
  echo "edllm-backend-${slot} edllm-frontend-${slot}"
}

slot_services() {
  local slot="$1"
  echo "backend_${slot} frontend_${slot}"
}

# `docker inspect` on the container's own healthcheck is the readiness signal:
# the backend probe already hits http://localhost:8000/health inside the
# container, so there is nothing to add from the host (and nginx:alpine has no
# curl to probe with).
wait_slot_healthy() {
  local slot="$1" container state
  for container in $(slot_containers "$slot"); do
    log "waiting for ${container} to report healthy"
    local i
    for ((i = 1; i <= READY_ATTEMPTS; i++)); do
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$container" 2>/dev/null || echo "missing")"
      case "$state" in
        healthy)
          log "${container}: healthy"
          break
          ;;
        unhealthy)
          log "${container}: UNHEALTHY — last probe output:"
          docker inspect -f '{{range .State.Health.Log}}{{.Output}}{{end}}' "$container" 2>/dev/null | tail -n 20
          return 1
          ;;
        exited | dead)
          log "${container}: ${state} — container logs:"
          docker logs --tail 50 "$container" 2>&1 || true
          return 1
          ;;
      esac
      if [ "$i" -eq "$READY_ATTEMPTS" ]; then
        log "${container}: still '${state}' after $((READY_ATTEMPTS * READY_SLEEP))s"
        docker logs --tail 50 "$container" 2>&1 || true
        return 1
      fi
      sleep "$READY_SLEEP"
    done
  done

  # One cross-service probe over edu-network, run from inside the target backend
  # container. Proves that DNS + networking between the two new containers works
  # before nginx is told to trust them.
  if ! compose exec -T "backend_${slot}" \
    wget -q --spider "http://frontend_${slot}:3000/" 2>/dev/null; then
    log "backend_${slot} cannot reach frontend_${slot} over edu-network"
    return 1
  fi
  log "slot ${slot} is ready (both containers healthy, network verified)"
  return 0
}

start_slot() {
  local slot="$1"
  log "== starting the ${slot} slot on ${IMAGE_TAG} =="
  # shellcheck disable=SC2086  # deliberate word splitting of the service list
  compose up -d --force-recreate $(slot_services "$slot")
}

# Used to undo a target slot that never went live: stop AND remove, so it holds
# neither memory nor a reference to its image.
remove_slot() {
  local slot="$1"
  log "removing the ${slot} slot"
  # shellcheck disable=SC2086
  compose stop $(slot_services "$slot") || true
  # shellcheck disable=SC2086
  compose rm -f $(slot_services "$slot") || true
}

# Used to retire the slot that just handed over. `stop` (not `rm`) respects
# stop_grace_period, so gunicorn drains in-flight requests and open SSE streams
# before the container dies, and the container stays around for a fast revert.
stop_slot() {
  local slot="$1"
  log "== draining and stopping the old ${slot} slot =="
  # shellcheck disable=SC2086
  compose stop $(slot_services "$slot")
}

# ---------- smoke-test (через nginx: проверяет весь путь, а не только апстрим) ----------
smoke_test() {
  local ok_health=false ok_docs=false
  for i in $(seq 1 "$SMOKE_ATTEMPTS"); do
    if [ "$ok_health" = false ] && curl -fsS $SMOKE_RESOLVE "$SMOKE_URL_HEALTH" > /dev/null; then
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
# The late-failure path: the old slot is already stopped, so there is nothing to
# switch back to and the previous images have to be put back on the ACTIVE slot.
rollback() {
  local good_sha="$1"
  log "== ROLLBACK to $good_sha on the ${ACTIVE_SLOT} slot (no rebuild, images already local) =="
  export IMAGE_TAG="$good_sha"

  # shellcheck disable=SC2086
  compose up -d --force-recreate $(slot_services "$ACTIVE_SLOT")
  wait_slot_healthy "$ACTIVE_SLOT" || log "WARNING: rolled-back slot never reported healthy"
  switch_upstream "$ACTIVE_SLOT" || log "WARNING: could not repoint nginx at ${ACTIVE_SLOT}"

  docker tag "edllm-backend:${good_sha}" edllm-backend:local || true
  docker tag "edllm-frontend:${good_sha}" edllm-frontend:local || true
  # shellcheck disable=SC2086
  compose up -d --force-recreate $WORKER_SERVICES || log "WARNING: workers did not come back on ${good_sha}"

  record_active_slot "$ACTIVE_SLOT"
  maintenance_is_on && maintenance_off

  if smoke_test; then
    log "rollback OK, $good_sha is running again"
    exit 1 # деплой всё равно считается провалившимся — job должен быть красным
  fi
  log "rollback ALSO FAILED — manual intervention required NOW"
  exit 2
}

# ---------- argument handling ----------
case "${1:-}" in
  --self-test)
    self_test
    exit $?
    ;;
  --switch)
    TARGET="${2:?usage: deploy.sh --switch blue|green}"
    case "$TARGET" in blue | green) ;; *) die "unknown slot '${TARGET}' (expected blue|green)" ;; esac
    switch_upstream "$TARGET" || die "could not switch to ${TARGET}"
    record_active_slot "$TARGET"
    log "active slot is now ${TARGET} (containers were NOT started — do that first if it is down)"
    exit 0
    ;;
  --init-state)
    # Bootstrap for a fresh clone, where the generated (git-ignored) files do not
    # exist yet and nginx would refuse to start on the missing include. Writes
    # them and stops — no containers touched, no reload, so it is safe to run
    # before anything is up.
    TARGET="${2:-$(recorded_slot)}"
    case "$TARGET" in blue | green) ;; *) die "unknown slot '${TARGET}' (expected blue|green)" ;; esac
    render_upstream "$TARGET"
    render_prometheus_targets "$TARGET"
    record_active_slot "$TARGET"
    log "generated state written for the ${TARGET} slot:"
    log "  ${UPSTREAM_FILE}"
    log "  ${PROM_TARGETS_FILE}"
    log "  ${SLOT_FILE}"
    exit 0
    ;;
  "" | -*)
    die "usage: deploy.sh <git_sha_short> | --switch blue|green | --init-state [slot] | --self-test"
    ;;
esac

SHA="$1"
export IMAGE_TAG="$SHA"

# Must come before the first read of the slot: a `git pull` can legitimately
# remove the generated files (they are git-ignored), and a fresh clone never had
# them. Re-creates them from $STATE_DIR/active_slot, never inventing a slot.
ensure_generated_state

ACTIVE_SLOT="$(resolve_active_slot)"
TARGET_SLOT="$(other_slot "$ACTIVE_SLOT")"
GOOD_SHA=""
[ -r "$LAST_GOOD_FILE" ] && GOOD_SHA="$(tr -d '[:space:]' < "$LAST_GOOD_FILE")"

# STAGE drives what the EXIT trap has to undo. It is advanced only after the
# step it names has actually succeeded.
STAGE="init"
MAINTENANCE_ENGAGED=false

cleanup_on_failure() {
  local code=$?
  [ "$code" -eq 0 ] && return 0

  case "$STAGE" in
    target_up)
      log "== FAILED before the switch — production is untouched on ${ACTIVE_SLOT} =="
      remove_slot "$TARGET_SLOT"
      ;;
    switched)
      log "== FAILED after the switch — sending traffic back to ${ACTIVE_SLOT} =="
      switch_upstream "$ACTIVE_SLOT" || log "WARNING: could not revert the upstream — check nginx NOW"
      remove_slot "$TARGET_SLOT"
      ;;
    *)
      log "== FAILED at stage '${STAGE}' =="
      ;;
  esac

  if [ "$MAINTENANCE_ENGAGED" = true ] && maintenance_is_on; then
    maintenance_off || log "WARNING: maintenance flag is still ON — clear it with deploy/maintenance.sh off"
  fi
  log "deploy of ${SHA} failed (exit ${code})"
}
trap cleanup_on_failure EXIT

mkdir -p "$STATE_DIR"
log "== deploying ${SHA}: ${ACTIVE_SLOT} (live) -> ${TARGET_SLOT} (target) =="

# ---------- 1. сборка новых образов под sha ----------
log "== build backend + frontend ($SHA) =="
compose build "backend_${TARGET_SLOT}"
compose build "frontend_${TARGET_SLOT}"

# ---------- 2. миграции: сначала проверка на совместимость, потом дамп ----------
log "== checking for pending migrations =="
CURRENT_REV="$(compose --profile migrate run --rm -T migrate \
  alembic current 2> /dev/null | tail -n1 | awk '{print $1}')"
HEAD_REV="$(compose --profile migrate run --rm -T migrate \
  alembic heads 2> /dev/null | tail -n1 | awk '{print $1}')"

log "current=${CURRENT_REV:-<empty>} head=$HEAD_REV"

if [ "$CURRENT_REV" != "$HEAD_REV" ]; then
  log "== migration guard: are the pending revisions safe for a live switch? =="
  GUARD_RC=0
  compose --profile migrate run --rm -T migrate \
    python -m app.scripts.migration_guard --current "$CURRENT_REV" --head "$HEAD_REV" || GUARD_RC=$?

  case "$GUARD_RC" in
    0) log "migration guard: additive — deploying live" ;;
    1 | 3)
      if [ "${DEPLOY_ALLOW_UNSAFE_MIGRATION:-0}" != "1" ]; then
        die "migration guard refused this release (rc=${GUARD_RC}).
  Nothing was migrated and production still runs the previous version.
  Either split the destructive step into a follow-up release (expand now,
  contract next), or re-run with DEPLOY_ALLOW_UNSAFE_MIGRATION=1 to deploy
  behind the maintenance page. See docs/DECISIONS.md §53."
      fi
      log "== DEPLOY_ALLOW_UNSAFE_MIGRATION=1: going through the maintenance page =="
      MAINTENANCE_ENGAGED=true
      maintenance_on
      ;;
    *) die "migration guard could not run (rc=${GUARD_RC}) — refusing to migrate blind" ;;
  esac

  log "== pending migration detected, dumping DB before upgrade =="
  DUMP_NAME="pre-migrate-${SHA}-$(date +%Y%m%d-%H%M%S).dump"
  # переиспользуем сервис db_backup: у него уже смонтирован volume db_backups
  # и заданы PGHOST/PGUSER/PGPASSWORD/PGDATABASE — просто подменяем entrypoint
  # с вечного цикла на разовый pg_dump
  compose run --rm -T --entrypoint sh db_backup -c \
    "pg_dump -Fc -f /backups/${DUMP_NAME} && echo written:${DUMP_NAME}"
  log "backup saved: ${DUMP_NAME} (in db_backups volume)"

  log "== applying migrations =="
  compose --profile migrate run --rm migrate
else
  log "== no pending migrations, skipping guard + dump + upgrade =="
fi

# ---------- 3. поднять целевой слот и дождаться готовности ----------
start_slot "$TARGET_SLOT"
STAGE="target_up"
wait_slot_healthy "$TARGET_SLOT" || die "the ${TARGET_SLOT} slot never became ready"

# ---------- 4. переключить nginx на новый слот ----------
switch_upstream "$TARGET_SLOT" || die "nginx would not take the ${TARGET_SLOT} slot"
STAGE="switched"

if [ "$MAINTENANCE_ENGAGED" = true ]; then
  maintenance_off
  MAINTENANCE_ENGAGED=false
fi

# ---------- 5. smoke-test уже через nginx ----------
smoke_test || die "smoke-test failed against the ${TARGET_SLOT} slot"

# ---------- 6. Celery: retag :local ПЕРЕД пересозданием ----------
# The workers resolve `edllm-backend:${IMAGE_TAG:-local}`, and a plain `restart`
# would keep them on the old image — they must be RECREATED. Retagging :local
# first keeps a bare `up -d` (the manual §7 order) on the deployed code too.
STAGE="workers"
log "== retag :local -> ${SHA} =="
docker tag "edllm-backend:${SHA}" edllm-backend:local
docker tag "edllm-frontend:${SHA}" edllm-frontend:local

log "== recreating Celery workers + flower on ${SHA} (warm SIGTERM, then acks_late re-queues) =="
# shellcheck disable=SC2086
if ! compose up -d --force-recreate $WORKER_SERVICES; then
  log "workers did not come up on ${SHA}"
  switch_upstream "$ACTIVE_SLOT" || log "WARNING: could not revert the upstream — check nginx NOW"
  remove_slot "$TARGET_SLOT"
  if [ -n "$GOOD_SHA" ]; then
    STAGE="rolling_back"
    rollback "$GOOD_SHA"
  fi
  die "workers failed and there is no last_good_sha to roll back to"
fi

# ---------- 7. погасить старый слот и записать состояние ----------
stop_slot "$ACTIVE_SLOT"
STAGE="done"
record_active_slot "$TARGET_SLOT"
echo "$SHA" > "$LAST_GOOD_FILE"
log "== deploy OK: ${SHA} live on the ${TARGET_SLOT} slot =="

# ---------- 8. ретенция образов ----------
# оставляем KEEP_IMAGES последних sha-тегов
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
