# shellcheck shell=bash
# Output for scripts/setup.sh. Every failure says what to do next, never just what broke.

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    \033[33mwarning:\033[0m %s\n' "$*" >&2; }

# die "what happened" "how to fix it"
die() {
  printf '\n\033[31merror:\033[0m %s\n' "$1" >&2
  if [ -n "${2:-}" ]; then printf '  fix: %s\n' "$2" >&2; fi
  exit 1
}
