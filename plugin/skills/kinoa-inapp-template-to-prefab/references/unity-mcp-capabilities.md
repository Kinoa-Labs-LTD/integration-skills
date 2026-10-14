# Unity MCP — capability map

| Capability | CoderGamester `mcp-unity` (prefix `mcp__mcp-unity__`) | CoplayDev `unity-mcp` (prefix `mcp__unity-mcp__` / `mcp__UnityMCP__`) | IvanMurzak `Unity-MCP` |
|---|---|---|---|
| liveness probe (read-only) | `get_scene_info` | `manage_editor` (action `get_state`) | `editor-application-get-state` |
| refresh / recompile | `recompile_scripts` | `refresh_unity` | `assets-refresh` |
| run a menu item | `execute_menu_item` | `execute_menu_item` | `reflection-method-call` on `Kinoa.InApps.Editor.KinoaInAppPrefabBuilder.BuildAll` |
| read console | `get_console_logs` | `read_console` | `console-get-logs` |
| inspect result | `get_gameobject` / file on disk | `manage_prefabs` / file on disk | `gameobject-find` / file on disk |

## Detecting the connected server

1. `ToolSearch` with query `unity` (max_results 20). Collect every returned tool name.
2. Classify by prefix / name:
   - names containing `mcp-unity__` → **CoderGamester mcp-unity**
   - names `manage_editor`, `refresh_unity`, `read_console` → **CoplayDev unity-mcp**
   - names `assets-refresh`, `console-get-logs`, `reflection-method-call` → **IvanMurzak Unity-MCP**
3. Call the liveness probe for that flavour. A transport error, a timeout, or
   "Unity Editor is not connected" ⇒ the Editor is not running / the bridge is
   down. Stop and tell the developer to open the project in Unity and start the
   MCP bridge (mcp-unity: `Tools/MCP Unity/Server Window → Start Server`).
4. Zero Unity tools found ⇒ no Unity MCP configured. Stop; point at the three
   servers' install docs. There is no offline fallback for Phase 6: the prefab
   is built by Unity, not by hand-written YAML.
