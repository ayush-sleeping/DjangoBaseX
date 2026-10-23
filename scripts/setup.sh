#!/usr/bin/env bash
# From a fresh clone to a signed-in application in one command (BUILD_ORDER 4.1, OPERATIONS.md § 2).
#
#   ./scripts/setup.sh                 Docker: env files, Postgres + Redis, migrate, first account,
#                                      both apps, then proves they answer
#   ./scripts/setup.sh --no-docker     the same env files and database steps on the host (uv, npm),
#                                      SQLite (ADR-0005); prints how to start the two dev servers
#   ./scripts/setup.sh --reset         stop this checkout's stack and DELETE its database volume
#                                      (asks for the project name, typed back)
#
#   --yes                    accept the derived project name without asking (implied by CI or no TTY)
#   --admin-email ADDRESS    the first account (default admin@example.com)
#
# Needs python3 3.9 or newer on the host (stock macOS has 3.9): it writes the env files before
# anything is installed. DBX_HEALTH_TIMEOUT (seconds, default 240) bounds each wait for the stack.
#
# Idempotent and safe to re-run: every step checks whether it is done. It never overwrites a
# secret, only fills keys that are empty or hold a placeholder, keeps its port choices in .env, and
# never touches a staging or production env file. Secret values are never printed; the
# development administrator's password is the one exception, shown once when the account is made.

set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LIB="$REPO/scripts/lib"
# shellcheck source=lib/log.sh
. "$LIB/log.sh"
# shellcheck source=lib/project.sh
. "$LIB/project.sh"
# shellcheck source=lib/ports.sh
. "$LIB/ports.sh"

ROOT_ENV="$REPO/.env"
BACKEND_ENV="$REPO/backend/.env"
FRONTEND_ENV="$REPO/frontend/.env.local"
HEALTH_TIMEOUT=${DBX_HEALTH_TIMEOUT:-240}
DISK_FLOOR_GB=${DBX_DISK_FLOOR_GB:-2}

ASSUME_YES=0 USE_DOCKER=1 RESET=0 ADMIN_EMAIL=admin@example.com
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-docker) USE_DOCKER=0 ;;
    --reset) RESET=1 ;;
    --admin-email) ADMIN_EMAIL=${2:?--admin-email needs an address}; shift ;;
    # The header comment above, and nothing after it.
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) die "unknown option: $1" "./scripts/setup.sh --help" ;;
  esac
  shift
done

INTERACTIVE=1
if [ -n "${CI:-}" ] || [ ! -t 0 ]; then INTERACTIVE=0; fi

envfile() { python3 "$LIB/envfile.py" "$@"; }
# In development the boot audit lists every production-only setting on each manage.py run. That
# is expected here and is noise in setup's output; `manage.py check` still shows the full list.
quiet_audit() { { grep -Ev '^(cfg\.[EW][0-9]+ |  Fix:)' || true; } | sed 's/^/    /'; }
# -p always: an exported COMPOSE_PROJECT_NAME must never point setup (or --reset's down -v) at
# another checkout's stack. PROJECT is set by identity(), or by reset().
compose() {
  docker compose --project-directory "$REPO" -f "$REPO/docker-compose.yml" -p "${PROJECT:?}" "$@"
}

# --- 1. Preflight --------------------------------------------------------------------------------

preflight() {
  step "Preflight"
  command -v python3 >/dev/null 2>&1 \
    || die "python3 not found" "install Python 3.9 or newer, then re-run ./scripts/setup.sh"
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
    || die "python3 is older than 3.9" "install Python 3.9 or newer, then re-run"
  if [ "$USE_DOCKER" = 1 ]; then
    command -v docker >/dev/null 2>&1 \
      || die "docker not found" "install Docker Desktop (or Docker Engine), or re-run with --no-docker"
    docker compose version >/dev/null 2>&1 \
      || die "Docker Compose v2 not found ('docker compose', not 'docker-compose')" \
             "update Docker Desktop, or install the compose plugin"
    docker info >/dev/null 2>&1 \
      || die "the Docker daemon is not running" "start Docker Desktop, then re-run ./scripts/setup.sh"
  else
    command -v uv >/dev/null 2>&1 || die "uv not found" "install it: https://docs.astral.sh/uv/"
    command -v npm >/dev/null 2>&1 || die "npm not found" "install Node.js 22, then re-run"
  fi
  local free_kb
  free_kb=$(df -Pk "$REPO" | awk 'NR==2 {print $4}')
  if [ "$free_kb" -lt $((DISK_FLOOR_GB * 1024 * 1024)) ]; then
    die "less than ${DISK_FLOOR_GB} GB free on $(df -P "$REPO" | awk 'NR==2 {print $6}')" \
        "free some space, or set DBX_DISK_FLOOR_GB lower"
  fi
  info "ok"
}

# --- 2. Identity ---------------------------------------------------------------------------------

identity() {
  step "Identity"
  local existing slug
  existing=$(envfile get "$ROOT_ENV" COMPOSE_PROJECT_NAME)
  if [ -n "$existing" ]; then
    SLUG=${existing%-dev}
    PROJECT=$existing
    info "project $existing (from .env)"
    return
  fi
  slug=$(project_slug "$(basename "$REPO")") \
    || die "cannot derive a project name from the directory '$(basename "$REPO")'" \
           "rename the directory to letters, digits and dashes, then re-run"
  if [ "$ASSUME_YES" = 0 ] && [ "$INTERACTIVE" = 1 ]; then
    printf '    Project name %s (containers %s-dev-*). Use it? [Y/n] ' "$slug" "$slug"
    local answer
    read -r answer
    case "$answer" in [nN]*) die "stopped" "rename the directory, then re-run" ;; esac
  fi
  SLUG=$slug
  PROJECT=$(project_name "$SLUG" dev)
  info "project $PROJECT"
}

# --- 3–5. Env files, ports and secrets -----------------------------------------------------------

port_ok() {  # free, or already published by this checkout's own stack
  port_free "$1" && return 0
  [ "$USE_DOCKER" = 1 ] || return 1
  compose port "$2" "$3" 2>/dev/null | grep -q ":$1\$"
}

choose_port() {  # choose_port KEY DEFAULT SERVICE CONTAINER_PORT
  local key=$1 default=$2 current chosen
  current=$(envfile get "$ROOT_ENV" "$key")
  if [ -n "$current" ] && port_ok "$current" "$3" "$4"; then
    info "kept $key=$current"
    return
  fi
  [ -n "$current" ] && warn "$key=$current is taken by something else; choosing another"
  chosen=$(pick_port "${current:-$default}") \
    || die "no free port near ${current:-$default} for $key" "set $key in .env to a free port"
  envfile set "$ROOT_ENV" "$key" "$chosen" >/dev/null
  info "set $key=$chosen"
}

# Postgres reads POSTGRES_PASSWORD only when its volume is first created. A password generated now,
# against a volume that already exists, would lock setup out of its own database: stop before
# writing anything, so restoring the old .env is a plain copy back.
refuse_orphaned_volume() {
  [ "$USE_DOCKER" = 1 ] || return 0
  envfile needs-secret "$ROOT_ENV" POSTGRES_PASSWORD hex || return 0
  docker volume inspect "${PROJECT}_pgdata" >/dev/null 2>&1 || return 0
  local separate="rename this directory (a new name is a new stack)"
  if [ -n "$(envfile get "$ROOT_ENV" COMPOSE_PROJECT_NAME)" ]; then
    separate="give COMPOSE_PROJECT_NAME in .env a new name"
  fi
  die "the database volume ${PROJECT}_pgdata already exists, but .env has no POSTGRES_PASSWORD
       for it. Postgres set its password when that volume was created and would refuse a new one" \
      "restore the .env that created it; or DELETE that database with ./scripts/setup.sh --reset;
       or, to keep it and start a separate stack, $separate. Then re-run"
}

env_files() {
  step "Env files"
  envfile refuse-production "$BACKEND_ENV" \
    || die "refusing to touch backend/.env" \
           "if this is a development checkout, add APP_ENV=development to backend/.env, then re-run"
  refuse_orphaned_volume
  envfile ensure "$ROOT_ENV" | sed 's/^/    /'
  envfile fill "$ROOT_ENV" COMPOSE_PROJECT_NAME "$(project_name "$SLUG" dev)" | sed 's/^/    /'
  envfile fill "$ROOT_ENV" AUTH_COOKIE_PREFIX "$(cookie_prefix "$SLUG")" | sed 's/^/    /'
  envfile secret "$ROOT_ENV" POSTGRES_PASSWORD hex | sed 's/^/    /'
  envfile secret "$ROOT_ENV" REDIS_PASSWORD hex | sed 's/^/    /'

  envfile ensure "$BACKEND_ENV" --from "$REPO/backend/.env.example" | sed 's/^/    backend: /'
  envfile fill "$BACKEND_ENV" APP_ENV development | sed 's/^/    backend: /'
  # Per checkout, from the directory (CONFIGURATION.md § 7): two worktrees keep separate cookies
  # and cache keys. PRODUCT_NAME is the owner's to set; until then the sign-in page says so.
  envfile fill "$BACKEND_ENV" PRODUCT_SLUG "$SLUG" | sed 's/^/    backend: /'
  # The host runserver (--no-docker) reads it from here; compose passes the same value. It must
  # equal the frontend's, or the client cannot find the CSRF cookie and every write fails.
  envfile fill "$BACKEND_ENV" AUTH_COOKIE_PREFIX "$(cookie_prefix "$SLUG")" \
    | sed 's/^/    backend: /'
  envfile secret "$BACKEND_ENV" SECRET_KEY django | sed 's/^/    backend: /'
  envfile secret "$BACKEND_ENV" JWT_SIGNING_KEY jwt | sed 's/^/    backend: /'
  envfile secret "$BACKEND_ENV" MFA_ENCRYPTION_KEY fernet | sed 's/^/    backend: /'

  envfile ensure "$FRONTEND_ENV" --from "$REPO/frontend/.env.example" | sed 's/^/    frontend: /'
  envfile fill "$FRONTEND_ENV" NEXT_PUBLIC_AUTH_COOKIE_PREFIX "$(cookie_prefix "$SLUG")" \
    | sed 's/^/    frontend: /'

  step "Ports"
  if [ "$USE_DOCKER" = 1 ]; then
    choose_port API_PORT 8000 backend 8000
    choose_port WEB_PORT 3000 frontend 3000
    choose_port DB_PORT 5432 db 5432
  else
    info "the host dev servers use 8000 and 3000 (runserver, next dev)"
  fi
}

# --- 7–10. Dependencies, migrate, seed, first account --------------------------------------------

first_account() {  # first_account <run-a-manage.py-command...>
  local out has_users password
  # The answer behind a marker, not on the last line: nothing Django or compose logs around it
  # can be mistaken for it.
  out=$("$@" shell -c \
    "from django.contrib.auth import get_user_model as m; print('DBX_HAS_USERS=%s' % m().objects.exists())" \
    2>&1) || {
    printf '%s\n' "$out" | quiet_audit | tail -n 30 >&2
    die "could not query users" \
        "fix the error above (is the database up and migrated?), then re-run ./scripts/setup.sh"
  }
  has_users=$(printf '%s\n' "$out" | sed -n 's/^DBX_HAS_USERS=//p' | tail -n 1)
  case "$has_users" in
    True|False) ;;
    *)
      printf '%s\n' "$out" | quiet_audit | tail -n 30 >&2
      die "could not tell whether an account exists" \
          "fix the error above, then re-run ./scripts/setup.sh"
      ;;
  esac
  if [ "$has_users" = "True" ]; then
    info "an account exists; bootstrap_admin skipped (it refuses once any user exists)"
    return
  fi
  envfile secret "$ROOT_ENV" DEV_ADMIN_PASSWORD password >/dev/null
  password=$(envfile get "$ROOT_ENV" DEV_ADMIN_PASSWORD)
  # The password travels in the environment, never in an argument (process list, shell history).
  BOOTSTRAP_ADMIN_PASSWORD=$password "$@" bootstrap_admin --email "$ADMIN_EMAIL" --no-input 2>&1 \
    | quiet_audit
  CREATED_ADMIN=1
}

# up_and_wait "what" [UP_OPTION | SERVICE]...: `compose up -d --wait`, bounded by HEALTH_TIMEOUT.
# A failure or a timeout shows the services' last log lines and the fix, where set -e alone would
# stop at compose's one-line error.
up_and_wait() {
  local what=$1 arg services=()
  shift
  for arg in "$@"; do
    case "$arg" in -*) ;; *) services+=("$arg") ;; esac
  done
  compose up -d --wait --wait-timeout "$HEALTH_TIMEOUT" "$@" && return 0
  warn "$what did not become healthy within ${HEALTH_TIMEOUT}s. The last log lines:"
  compose logs --tail 30 ${services[@]+"${services[@]}"} >&2 || true
  die "$what did not start" \
      "fix the error above, then re-run ./scripts/setup.sh (a slow machine: DBX_HEALTH_TIMEOUT=600)"
}

database_docker() {
  # Compose builds only a missing image, so without this a re-run after a pull that changed a
  # Dockerfile or a lockfile keeps the stale image. Cached, it takes seconds when nothing changed.
  # The stale node_modules volume is the other half: start_and_prove's --renew-anon-volumes.
  step "Build the app images"
  compose build backend frontend
  step "Database and cache"
  up_and_wait "the database and cache" db redis
  step "Migrate (seeds the permission catalog and system roles)"
  # run --rm, never on container start (OPERATIONS.md § 2 step 8).
  compose run --rm -T backend uv run --frozen python manage.py migrate --noinput 2>&1 | quiet_audit
  step "First account"
  first_account compose run --rm -T -e BOOTSTRAP_ADMIN_PASSWORD backend \
    uv run --frozen python manage.py
}

database_host() {
  step "Backend dependencies"
  (cd "$REPO/backend" && uv sync --frozen)
  step "Migrate (seeds the permission catalog and system roles)"
  (cd "$REPO/backend" && uv run --frozen python manage.py migrate --noinput) 2>&1 | quiet_audit
  step "First account"
  first_account host_manage
  step "Frontend dependencies"
  (cd "$REPO/frontend" && npm ci --no-audit --no-fund)
}

host_manage() { (cd "$REPO/backend" && uv run --frozen python manage.py "$@"); }

# --- 11–13. Start, prove it, say what next -------------------------------------------------------

wait_for() {  # wait_for NAME URL SERVICE
  local deadline=$((SECONDS + HEALTH_TIMEOUT))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ "$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' "$2" || true)" = "200" ]; then
      info "$1 answers: $2"
      return 0
    fi
    sleep 2
  done
  warn "$1 did not answer within ${HEALTH_TIMEOUT}s. Its last log lines:"
  compose logs --tail 30 "$3" >&2 || true
  die "$1 is not answering at $2" "fix the error above, then re-run ./scripts/setup.sh"
}

start_and_prove() {
  step "Start"
  # --renew-anon-volumes: node_modules and .next are anonymous volumes (frontend/Dockerfile.dev).
  # Without it compose carries the old ones into the container it recreates for a rebuilt image,
  # so a lockfile change would stay hidden behind the previous node_modules.
  up_and_wait "the stack" --renew-anon-volumes
  local api web
  api=$(envfile get "$ROOT_ENV" API_PORT)
  web=$(envfile get "$ROOT_ENV" WEB_PORT)
  step "Prove it"
  wait_for "the API" "http://127.0.0.1:$api/api/health/" backend
  wait_for "the frontend" "http://127.0.0.1:$web/login" frontend
  step "Ready"
  info "App:       http://localhost:$web"
  info "API docs:  http://localhost:$api/api/docs/"
  say_account
  info "Development warnings from the boot audit are hidden above: manage.py check lists them."
  info "Next: documentation/NEW_PROJECT.md"
}

say_account() {
  if [ "${CREATED_ADMIN:-0}" = 1 ]; then
    info "Sign in:   $ADMIN_EMAIL  /  $(envfile get "$ROOT_ENV" DEV_ADMIN_PASSWORD)"
    info "           (development only; it is also kept as DEV_ADMIN_PASSWORD in .env)"
  elif [ -n "$(envfile get "$ROOT_ENV" DEV_ADMIN_PASSWORD)" ]; then
    info "Sign in:   the account setup made first; its password is DEV_ADMIN_PASSWORD in .env"
  fi
}

# --- --reset -------------------------------------------------------------------------------------

reset() {
  local name typed slug var
  name=$(envfile get "$ROOT_ENV" COMPOSE_PROJECT_NAME)
  if [ -z "$name" ]; then
    # A lost .env: the name setup derives from the directory, which is the stack it left behind.
    # Typing it back below confirms it.
    slug=$(project_slug "$(basename "$REPO")") \
      || die "no COMPOSE_PROJECT_NAME in .env, and none derivable from the directory" ""
    name=$(project_name "$slug" dev)
  fi
  PROJECT=$name
  [ "$INTERACTIVE" = 1 ] \
    || die "--reset deletes data and needs a person at a terminal" "run it in an interactive shell"
  step "Reset $name"
  info "This stops $name and DELETES its database volume (${name}_pgdata)."
  info "Env files and secrets are kept. Type the project name to confirm:"
  printf '    > '
  read -r typed
  [ "$typed" = "$name" ] || die "the name did not match; nothing was deleted" ""
  # Compose resolves the whole file even for `down`, and refuses on a missing ${X:?}: a lost .env,
  # the case --reset exists for, has none. Stand-ins for the absent ones only (`down` uses none of
  # them), never overriding a value .env has.
  for var in POSTGRES_PASSWORD REDIS_PASSWORD AUTH_COOKIE_PREFIX; do
    [ -n "$(envfile get "$ROOT_ENV" "$var")" ] || export "$var=unused-by-down"
  done
  compose down -v
  info "done. Re-run ./scripts/setup.sh to start fresh."
}

# --- main ----------------------------------------------------------------------------------------

if [ "$RESET" = 1 ]; then
  preflight
  reset
  exit 0
fi

preflight
identity
env_files
if [ "$USE_DOCKER" = 1 ]; then
  database_docker
  start_and_prove
else
  database_host
  step "Ready (no Docker)"
  info "Start the API:       cd backend && uv run python manage.py runserver"
  info "Start the frontend:  cd frontend && npm run dev"
  info "Then open http://localhost:3000"
  say_account
  info "Next: documentation/NEW_PROJECT.md"
fi
