# Claude Tools Config

Local web UI to view and toggle Claude Code skills, plugins and MCP servers globally and per project.

Run: `python3 app.py [project]` (Windows: `py app.py [project]`; opens the browser). `project` defaults to the current folder, except the tool's own folder.
The start project is pushed to the top of recent history; the UI opens the most recent project. Tests: `python3 -m unittest`.

## Windows

- Claude Code may store one project in `~/.claude.json` under several keys (`C:\x`, `C:/x`, `c:/x`). Keys are matched with
  `normalize_path` (normcase + normpath); reads merge all matching entries, writes go to all of them, a new entry uses `C:/x`.
- JSON is always written with `\n` line endings. Pasted paths may be wrapped in quotes; they are stripped.
- Static files use an explicit content-type map (the Windows registry can break `mimetypes`).

## Stack

- Python 3.14, standard library only (`http.server`, `dataclasses`, `enum`). No pip dependencies.
- Frontend: one `static/index.html` + vanilla `app.js` + `style.css`. No build step.
- Server binds to `127.0.0.1` only. Every `/api` request must carry header `X-Claude-Tools-Config: 1`.
- `POST /api/shutdown` (power button in the header) stops the server after the current write finishes.

## Layout

| File | Purpose |
|---|---|
| `app.py` | entry point: start server, open browser |
| `claude_tools_config/dto.py` | dataclass DTOs and enums for every API input/output |
| `claude_tools_config/paths.py` | locations of Claude Code files (built from a `home` dir, so tests use a fake home) |
| `claude_tools_config/store.py` | JSON read / patch-one-key write with backup |
| `claude_tools_config/pool.py` | global pool: skills, plugins, MCP |
| `claude_tools_config/project.py` | effective project state and project overrides |
| `claude_tools_config/history.py` | recent projects |
| `claude_tools_config/batch.py` | apply one change to many items; collects per-item errors |
| `claude_tools_config/presets.py` | named sets of project overrides in `~/.config/claude-tools-config/presets.json` |
| `claude_tools_config/server.py` | HTTP routes, `ErrorDto` responses |

## Data model

Global pool (left panel) = everything installed, with its global value:

| Kind | Pool source | Global value |
|---|---|---|
| skill | `~/.claude/skills/<dir>/SKILL.md` (id = dir name) + claude.ai skills `~/.claude/skills/synced/<bucket>/<dir>/SKILL.md` (id = `anthropic-skills:<dir>`) | `skillOverrides[id]` in `~/.claude/settings.json`; missing = `on` |
| plugin | `~/.claude/plugins/installed_plugins.json` + `~/.claude/skills/<dir>/.claude-plugin/plugin.json` (id `<dir>@skills-dir`) + keys of user `enabledPlugins` | `enabledPlugins[id]` in `~/.claude/settings.json`; missing = `off` |
| mcp | top-level `mcpServers` in `~/.claude.json` (= on) + `~/.config/claude-tools-config/mcp-pool.json` (= off) | on / off |

Skill values: `on`, `name-only`, `user-invocable-only`, `off`. Plugin and MCP values: `on`, `off`.
A skill with `disable-model-invocation: true` in SKILL.md is locked by its author: Claude Code ignores `skillOverrides` for it,
so the app shows it as `user-invocable-only` with a lock icon and refuses to change it.

Project (right panel) shows every item with its effective value; enabled items first. Each item either inherits or overrides.
Overrides are written only to personal files; `<project>/.claude/settings.json` is read-only for this app.

| Kind | Project override location |
|---|---|
| skill | `skillOverrides` in `<project>/.claude/settings.local.json` |
| plugin | `enabledPlugins` in `<project>/.claude/settings.local.json` |
| mcp, user-scope server | `disabledMcpServers` (array of names) in `projects[<path>]` of `~/.claude.json` |
| mcp, server only in app pool | force on = copy definition into `projects[<path>].mcpServers` (local scope) |
| mcp, from `<project>/.mcp.json` | `disabledMcpjsonServers` in `<project>/.claude/settings.local.json` |

Precedence for skills and plugins: local settings → project `settings.json` → global.
A chosen value is always written explicitly, even if it equals the inherited or default value; only a reset removes the key.
Project `PUT` with `{"value": null}` resets the override (no DELETE for values). Global values never accept null.

Bulk actions apply to every selected item in the panel (all tabs), not only the visible ones.
A preset is a named list of project overrides (`kind`, `id`, `value`), stored in `presets.json`. Presets exist only for projects.
"Save" snapshots the project's current overrides; the presets dialog edits a preset's overrides without touching the project.
`POST /api/presets/{id}/apply?path=` writes all its overrides into the project on top of existing ones; missing items are reported per item.

Skills and MCP servers bundled in plugins are read-only children of the plugin card.

## Write rules

- Re-read the file right before writing and change only the needed key.
- Before a write, back up the file to `~/.config/claude-tools-config/backups/` if its last backup is older than 1 hour. Keep 10 backups per file; the backup name holds a hash of the full path.
- Write directly, no temp file. Keep the file's trailing-newline style, 2-space indent.
- Never delete an MCP definition that exists nowhere else: move it to `mcp-pool.json` first.
- Running `claude` sessions see changes only after restart.
- Mask `env` and `headers` values of MCP servers in API output (they hold secrets).
