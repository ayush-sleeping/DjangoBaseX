# shellcheck shell=bash
# Port choice (OPERATIONS.md § 2 step 3). Probed by binding, the only test that cannot be fooled.

# port_free <port>: exit 0 if nothing listens on 127.0.0.1:<port>
port_free() {
  python3 - "$1" <<'PY'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

# pick_port <preferred>: the first free port from <preferred> upward (100 tries)
pick_port() {
  local port=$1 last=$(($1 + 100))
  while [ "$port" -le "$last" ]; do
    if port_free "$port"; then
      printf '%s\n' "$port"
      return 0
    fi
    port=$((port + 1))
  done
  return 1
}
