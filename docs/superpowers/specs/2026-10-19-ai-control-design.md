# AI control (CLI + MCP) — design

Status: draft for approval, 2026-10-19.

## Intent

Let AI agents drive the iPhone through scrcrappy: look at the screen, tap, long-press, swipe, type. Two
interfaces over the same actions:

- **`scrcrappy agent …`**: one shell command per action, for any agent or script that can run commands
  (MCP isn't always available). Jailbreak (agent) mode only, because only there is a single action fast
  (no video, no Bluetooth start-up).
- **MCP server inside the running scrcrappy window**, both input modes. The user keeps scrcrappy open,
  watches the AI work in the normal window and can step in with the mouse; in Bluetooth / ESP32 mode the AI
  reuses the running video and pointer.

## Goals

- An AI loop of *screenshot → decide → act → screenshot* works with either interface.
- Coordinates are **percent of the screenshot's width and height** (0–100, decimals allowed), x left to
  right, y top to bottom of the upright screenshot: independent of resolution and of any resizing an AI
  client does to images.
- Screenshots come with their size and orientation.
- Failures are explicit (JSON error / MCP tool error with a readable reason), never silent.

## Non-goals (first version)

- Home / lock / app-switcher buttons, single key presses, pinch, "wait until the screen settles",
  opening apps, on-screen element lists (the agent can't provide these yet).
- The CLI in Bluetooth / ESP32 mode (each call would pay 5–10 s of start-up).
- An MCP server that the AI client launches itself (stdio); a remote / network-reachable server.

## Anti-goals

- Anything on the computer being able to control the phone without the user's say-so: the MCP endpoint is
  off by default, local only, and token-protected.
- Output an agent can't parse: no pygame banner or log lines on the CLI's stdout.

## Decided (user)

1. Actions: **screenshot** (PNG + size and orientation), **tap** x,y, **long-press** x,y[,ms],
   **swipe** x1,y1,x2,y2[,ms], **type text** into the focused field, **clipboard read** (agent mode only).
   Durations are an optional last value.
2. The CLI is its own command, `scrcrappy agent`, with one action option per call:

   ```sh
   scrcrappy agent --screenshot out.png
   scrcrappy agent --tap 32,25.5
   scrcrappy agent --long-press 32,25.5[,ms]
   scrcrappy agent --swipe 50,80,50,20[,ms]
   scrcrappy agent --type "hello"
   scrcrappy agent --clipboard
   ```

   The plain `scrcrappy [--mouse …]` usage stays as it is.
3. MCP is **option B**: the open scrcrappy window serves MCP. A Settings switch "Allow AI control" turns it
   on (saved in config.json); a `--mcp` launch flag turns it on for that run. You watch in the same window.
4. Clipboard read has a known limit: when iOS shows "Allow Paste" on the phone, the agent can't answer it.
   Keep the command; it fails with a clear message when the prompt blocks it.
5. **Typing in agent mode: keys first, paste as fallback.** Text a US layout can type (printable ASCII,
   Enter, Tab) is typed as one `key` command per character: no prompt, clipboard untouched. Text with
   anything else (accents, emoji) is typed with the agent's `text` (paste), which may show "Allow Paste" and
   replaces the clipboard. The reply says which was used (`"typed_with": "keys" | "paste"`). Decided
   per call, for the whole text, so the order of characters never mixes methods.
6. **Coordinates in percent** (0–100, decimals) of the upright screenshot, for both CLI and MCP.
7. **Input lock:** while an MCP tool call runs, the window ignores the user's mouse and keyboard; it's
   released as soon as the call ends.
8. **Status LED** while AI control is on: green = on, not in use; yellow = the AI is in a session;
   red = a command is running (input locked).

## My calls (builder may refine, user can veto)

- **Defaults:** long-press 1000 ms, swipe 300 ms, tap = down, 80 ms, up. Moves every ~16 ms.
- **Screenshot size cap:** screenshots are scaled down to at most 1568 px on the long edge (aspect kept),
  where AI clients start shrinking images anyway; coordinates are percent, so this changes nothing for
  them. The iPhone 8 (750×1334) is unaffected.
- **Orientation in Bluetooth / ESP32 mode:** only `portrait` or `landscape`, from the video frame's shape
  (there's no agent to ask which way it's turned).
- **No input (`--mouse none`):** AI control offers only `screenshot`.
- **Screenshot source:** agent mode uses the agent's lossless PNG turned upright; Bluetooth / ESP32 mode
  uses the current video frame (already upright). Orientation is reported as `portrait`,
  `portrait-upside-down`, `landscape-left` or `landscape-right`; size in pixels of that image.
- **Coordinates without a fresh screenshot:** the CLI asks the agent for the orientation and maps upright
  percentages to the agent's portrait fractions, reusing `geometry.to_device`. Coordinates outside 0–100
  are an error, not clamped.
- **CLI output:** one JSON object on stdout, e.g.
  `{"ok": true, "path": "out.png", "width": 750, "height": 1334, "orientation": "portrait"}`;
  on failure `{"ok": false, "error": "…"}` and exit code 1. Pairing prompts and hints go to stderr.
  The pygame banner is suppressed (`PYGAME_HIDE_SUPPORT_PROMPT`) before pygame is imported.
- **CLI touch readiness:** if the agent reports `touch_ready: false`, touch actions fail with
  "touch the phone's screen once (needed after each reboot)".
- **MCP transport:** Streamable HTTP, POST-only JSON responses (no SSE stream), implemented with the
  standard library (`http.server` + JSON-RPC: `initialize`, `notifications/initialized`, `ping`,
  `tools/list`, `tools/call`). No new dependency. Verified against Claude Code
  (`claude mcp add --transport http …`).
- **MCP endpoint:** `http://127.0.0.1:7331/mcp`, bound to 127.0.0.1 only. Every request needs
  `Authorization: Bearer <token>`; the token is random, created once, kept in config.json. Requests with a
  non-local `Origin` header are refused (DNS rebinding).
- **MCP tools:** `screenshot` (returns the PNG as MCP image content plus a text block with size and
  orientation), `tap`, `long_press`, `swipe`, `type_text`, `clipboard` (agent mode only; listed only then).
  In Bluetooth / ESP32 mode the tools drive the existing pointer (move, press, release) and keyboard;
  `type_text` reports characters it couldn't type (US layout, ASCII), as Paste does today.
- **Threading:** HTTP requests are served on a background thread; each tool call is handed to the window's
  thread and the request waits for its result. One tool call at a time.
- **Settings:** an "Allow AI control (MCP)" switch; when on, the panel shows the address and a **Copy**
  button that copies the ready-to-paste
  `claude mcp add --transport http scrcrappy http://127.0.0.1:7331/mcp --header "Authorization: Bearer …"`.
- **Watching:** each AI tap, long-press or swipe briefly draws a ring where it touched (about 0.6 s).
- **LED:** a small dot at the top of the pill, only while AI control is on; its tooltip explains the
  colours. "In a session" (yellow) = any MCP request in the last 30 s, since MCP over HTTP has no explicit
  conversation signal. Red wins over yellow while a tool call runs.
- **Human and AI together:** between tool calls the user's mouse and keyboard work as usual; during a call
  they're ignored (decision 7). Events that arrive during the lock are dropped, not replayed.
- **Busy port:** if 7331 is taken, AI control stays off and the reason is printed / shown in Settings.

## Left to the builder

- Module layout (e.g. `actions.py` shared by CLI and MCP, `mcp.py` for the server).
- Exact JSON-RPC error codes and tool input schemas (they follow the actions above).
- How the ring is drawn.
