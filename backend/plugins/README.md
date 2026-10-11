# backend/plugins/

Where a product's plugins live: one directory per plugin, each normally its own repository
mounted as a git submodule. `config/settings.py` installs every `*/plugin.toml` it finds here
(`core/plugins.py`, BUILD_ORDER 3.1), so adding a plugin edits no settings list.

```bash
cd backend
uv run python ../scripts/plugins.py new billing   # scaffold from scripts/plugin_template/
uv run python ../scripts/plugins.py link billing  # mount its frontend half
uv run python ../scripts/plugins.py list
```

Empty in the boilerplate. This file keeps the directory present, so the Docker dev stack can
mount it. For a worked example, see `examples/plugins/notes/`.
