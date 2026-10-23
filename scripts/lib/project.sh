# shellcheck shell=bash
# Project identity (OPERATIONS.md § 1): the ONE place a slug and a compose project name are made.

# project_slug "My Product_v2" -> my-product-v2   (lower-case [a-z0-9-], ≤ 36 so "<slug>-dev" ≤ 40)
project_slug() {
  local slug
  slug=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
  slug=${slug:0:36}
  slug=${slug%-}
  if [ -z "$slug" ] || ! printf '%s' "$slug" | grep -Eq '^[a-z0-9][a-z0-9-]*$'; then
    return 1
  fi
  printf '%s\n' "$slug"
}

# project_name <slug> <env> -> <slug>-<env>, the COMPOSE_PROJECT_NAME
project_name() {
  printf '%s-%s\n' "$1" "$2"
}

# cookie_prefix <slug> -> the AUTH_COOKIE_PREFIX: per checkout, so two stacks on localhost never
# share cookie names (cookies ignore the port).
cookie_prefix() {
  printf '%s\n' "$1" | tr '-' '_'
}
