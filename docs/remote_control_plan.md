# Remote control and web interface — design proposal

**Status: PROPOSED 2026-09-01. Not yet agreed.** This is a design document,
not a record of work done. Decisions and progress go in `CHANGELOG.md` and
the status log once the plan is accepted or amended.

## 1. Summary

Build the web interface strangler-fig style: the existing application
becomes a headless core that any client can drive, and the browser is one
such client alongside the CLI and the Qt GUI. The lab user keeps running
`python interface_run_me.py` exactly as today. The web server is an opt-in
flag on the same process, off by default, and the web dependencies are
imported only when that flag is given.

The single most important finding: **the seam already exists.**
`Interface._command_handler(command)` is the one dispatch point used by
the CLI, by the Qt GUI console, by the headless test suite, and by the
2025 web prototype on `feature/webapp`. Everything the browser needs to
*send* can go through it unchanged. What does not exist yet is the return
path: the core reports to the operator by `print()`, by Qt signals, and by
blocking `input()` prompts, none of which can cross a network. Fixing that
is Phase 0, and every item in it is already on `MODERNIZATION.md`.

Recommended stack: FastAPI + uvicorn in a thread inside the existing
process; one static HTML page with vanilla JavaScript and a vendored
plotting library, no build toolchain; Tailscale for the network path.

## 2. The request, restated

1. A web-app version of the controller, because the machine is in
   Melbourne, the operator is in Madrid, and Remote Desktop is heavy.
2. Diagnostics visible *during* acquisition, with clean displays.
3. Keep the local version working. Strangler-fig: a headless core that
   receives commands and reports to a web server.
4. The lab user should notice nothing until told there is a web option.
5. Adding features must stay as simple as writing code for the original,
   or simpler, because the hardware interfaces are still changing.

All five are achievable. Three of them have costs or preconditions that
change the shape of the plan; those are in the next section.

## 3. Pushback — things that change the plan

### 3.1 A web app does not solve reachability. The network path does.

A server bound to port 8000 on the lab PC is reachable from Madrid only
if there is a route to it. A university network will not allow inbound
connections, and Remote Desktop works today only because some path
already exists (a VPN, a gateway, or a port someone opened). The web app
needs the same path or a better one, and nothing in this repo can provide
it.

**Recommendation: Tailscale** on the lab PC and on each machine you work
from. It is an outbound-only WireGuard mesh: no inbound firewall rule, no
port forwarding, no IT ticket, free for personal use, and every device
gets a stable name. The dashboard is then `http://raman-pc:8000` from
anywhere, and only members of the tailnet can reach it at all. The
alternative is to keep using whatever path RDP uses and SSH-tunnel the
port through it, which works but keeps the heavy dependency you want rid
of.

This cannot be verified from here. **Open question for you:** how does
RDP reach the lab PC today, and can you install software on it?

### 3.2 A browser that drives a laser needs a safety and security story

RDP has the same exposure, so this is not a new risk, but a web page
lowers the barrier: a phone in a pocket, a tab left open, a shared link.
Proposed policy, cheapest first:

- Bind to localhost by default. Serving on the LAN or the tailnet is an
  explicit flag. Never expose it to the open internet.
- The tailnet is the authentication boundary. On top of that, write
  commands require a token; the status view and live spectra do not.
  Two access levels, nothing more.
- Reads are side-effect free. A status poll must never go through the
  command handler, because the handler carries the `@heartbeat` that
  resets the laser watchdog. A dashboard left open would otherwise keep
  the watchdog fed forever. (Moot with the Tiger, whose watchdog is a
  stub, but the design should not depend on that.)
- Consider a bench-side "remote control armed" toggle in the local GUI,
  with a timeout, so a remote operator can only *move* things when
  someone at the instrument has agreed. This is a policy decision for you
  and the student, not something the code should decide.

### 3.3 The core is not headless today

Measured against the current tree:

| Obstacle | Where | Why it blocks a remote client |
|---|---|---|
| PyQt5 imported by the core | `acqcontrol.py` (`spectrum_ready`), `pixiscam.py` (`temp_signal`), `datafit/laser_detection.py` (`peak_spectrum_ready`), `gui_services.py`, `logging_utils.py` | Every outbound event is a Qt signal. A web server has no Qt event loop to subscribe with, and `import microscope` currently drags in the whole GUI stack. |
| `print()` as the reporting channel | 69 sites in `microscope.py`, 26 in `acqcontrol.py`, 55 in `simulation.py` | Output goes to the terminal, not to the caller. `where_am_i` returns `None` and prints. The Qt GUI console already misses all of it (the stdout redirect in `pyqtGUI.py:1030` is commented out); RDP hides that gap because you can see the terminal. |
| Blocking `input()` in library code | 6 sites in `microscope.py`, 2 in `acqcontrol.py`, more in the calibration modules | A remote command that reaches `input()` would hang the hardware worker, or worse, steal the prompt from whoever is at the CLI. Already `MODERNIZATION.md` 2.1. |
| Errors returned as formatted strings | `_command_handler` | Callers string-match for `"Error"`; the headless test has to. A wire protocol needs `ok`/`value`/`error`. Already 2.4. |
| No single owner of the hardware | GUI runs commands on the Qt main thread; the scan runs on its own thread; the live camera runs on a third; `refresh_ui()` polls the TRIAX slit and the camera temperature on a timer | Nothing prevents two threads writing to one serial port. Today the protection is social: one person, one window. A second client makes the hazard real. |
| Two-place command registration | `@ui_callable` plus a hand-maintained `command_functions` dict, enforced by `_integrity_checker` | Works, but it is exactly the duplicated-registration smell the style guide names. Fixing it is what makes "add a method, it appears everywhere" true. |

One latent bug found on the way: `Interface.cli()` is `@thread_locked`,
so it holds `interface.lock` for the entire session. Any
`@interface_locked` method called from another thread waits forever.
Only the laser watchdog uses that decorator, and the Tiger's watchdog is
a stub, so it is dormant. The executor in Phase 0 replaces the lock and
removes the trap.

### 3.4 "Invisible to the lab user" is achievable, at a small visible cost

Every Phase 0 change is behaviour-preserving and gated by the existing
29 tests plus the new ones each step adds. Three of them alter what the
CLI user sees, slightly:

- Former `print()` lines arrive with a logger prefix (`[INFO]M. ...`).
- Confirmation prompts stay, but are supplied by the CLI layer rather
  than buried in the method. Same wording.
- A command typed while a scan is running is refused with a "busy"
  message instead of interleaving with the scan on the serial port. This
  is the one real behavioural change, and it is a fix.

### 3.5 What "simpler than the original" can and cannot mean

**Can:** a new command is one decorated method. It then appears in the
CLI, the `help` listing, the Qt console, the web console, and the
`GET /api/commands` listing with its docstring and argument names, with
no registration step. Likewise a new reported quantity is one decorated
property, and the status snapshot, the dashboard tiles, and the diagnostic
log pick it up on their own. That is the decorator story you asked for,
and it is the same "field metadata drives the UI" pattern used in the
TDS-app motor setup GUI.

**Cannot:** a new *kind* of display (a stage map, a peak-tracking plot)
is frontend work. The browser can render generic tiles and a generic
spectrum plot from the snapshot; anything bespoke is written once in
JavaScript. Keep that boundary honest.

### 3.6 Two things not to do

- **Do not build on `feature/webapp`.** It relocated the entire repo into
  `webapp/raman/services/` (218 renamed files), so it cannot be merged,
  and it carries Django + Channels + Daphne + Twisted + a database with
  migrations for a single-instrument dashboard that stores nothing. Its
  `get_instrument_status()` dict is a good inventory of what the
  dashboard needs, and its consumer shows the right message shapes. Mine
  both, then delete the branch.
- **Do not split hardware and web into two processes.** The PIXIS SDK is
  a singleton and the serial ports have one owner; inter-process
  messaging buys nothing for one instrument and doubles the failure
  modes. One process, web server in a thread.

## 4. Target architecture

```
                 ┌────────────────────────── one process on the lab PC ──────────────────────────┐
                 │                                                                                │
   CLI (stdin) ──┤►                                                                               │
                 │   Interface._command_handler ──► HardwareExecutor ──► Microscope / Laser /     │
   Qt GUI ───────┤►      (unchanged entry point)     (one worker thread,   Triax / PIXIS / Arduino│
                 │                                    owns all hardware)          │               │
   Web daemon ───┤►  FastAPI: REST + WebSocket             │                      │ publish       │
   (opt-in flag) │        ▲          ▲                     │ jobs: scan,          ▼               │
                 │        │          │                     │ live view       EventBus             │
   Python client─┤►       │          └──── subscribe ──────┴─────────────────  (thread-safe       │
   (scripting)   │        │                                                     pub/sub)          │
                 │        └──── read ──── StateCache ◄── subscribe ─────────────┘   │             │
                 │                        (last known value of every                │ subscribe   │
                 │                         reported quantity; no hardware)          ▼             │
                 │                                                          QtEventBridge → pyqtSignals
                 │                                                          DiagnosticLog → scan.jsonl
                 └────────────────────────────────────────────────────────────────────────────────┘
```

Five components, each small and separately testable:

- **CommandRegistry.** `@ui_callable` registers the method itself (name,
  docstring, `inspect.signature`). `command_functions` is derived, the
  hand-written dicts go, `_integrity_checker` becomes unnecessary.
  Arguments stay strings, as the CLI passes them today; type coercion
  from annotations is a later refinement, not a dependency.
- **HardwareExecutor.** One worker thread; `_command_handler` submits to
  it and waits, so CLI and GUI semantics are unchanged while every
  hardware touch is serialised. A scan is a job on the same worker with
  the existing `cancel_event`; while it runs, other commands are refused
  with a `CommandResult(ok=False, error="busy: scan running")`. Cancel and
  stop bypass the queue. The live-camera thread stays as it is for now
  and is noted as the remaining concurrent hardware user.
- **EventBus.** `publish(topic, payload)` / `subscribe(topic, callback)`,
  thread-safe, no Qt. Replaces the four `pyqtSignal`s, the
  `GUIEmitterService`, and the `status_cb`/`progress_cb` arguments.
  Topics: `log`, `spectrum`, `scan.progress`, `scan.status`,
  `camera.temperature`, `state.<name>`. The Qt GUI subscribes through a
  `QtEventBridge` that re-emits as signals, so GUI code changes only at
  its `connect()` lines.
- **StateCache.** Subscribes to `state.*` and holds the last value of
  every `@reported` quantity. `GET /api/status` reads this and nothing
  else. The executor publishes after each command and each scan step, so
  a dashboard never polls a serial port. (Today `refresh_ui()` does poll
  the TRIAX slit and the camera temperature on a timer, from the Qt main
  thread, while a scan may be using both.)
- **CommandResult.** `ok: bool`, `value`, `error`, `output: list[str]`
  (log lines emitted during the call). Returned by `_command_handler`;
  the CLI prints it, the GUI console shows it, the API serialises it.

Wire protocol, first cut:

| Endpoint | Purpose | Notes |
|---|---|---|
| `GET /api/status` | StateCache snapshot | no auth, no hardware |
| `GET /api/commands` | registry: name, doc, parameters | generated; the web console's `help` |
| `POST /api/command {text}` | run one command line | token; returns `CommandResult` |
| `GET/PUT /api/scan/parameters` | the four `acq_ctrl` parameter dicts | mirrors the Qt parameter tabs |
| `POST /api/scan/start`, `/cancel` | scan job | token |
| `WS /ws/events` | EventBus firehose | log, spectra, progress, state deltas |

Spectra are 1024 floats at a few hertz; JSON is fine and binary framing
can come later if it is ever needed. FastAPI generates the OpenAPI page
for free, which is the "clean interface" for scripting: a
`raman_client.py` that wraps these six calls is what lets you drive the
instrument from a Python prompt in Madrid.

## 5. Phased plan

Each phase ends with both test forms green: the unit suite and the
headless workflow suite. Nothing ships to the lab PC before Phase 0 is
complete, and Phase 0 on its own leaves the lab user with a strictly
better local application.

### Phase 0 — make the core headless (behaviour-preserving)

| # | Change | MODERNIZATION | Test that guards it |
|---|---|---|---|
| 0.1 | `CommandResult` returned by `_command_handler`; CLI/GUI print `.text` | 2.4 | headless suite asserts `.ok`, not `'Error' not in str(result)` |
| 0.2 | `print()` → logger in `microscope.py` and `acqcontrol.py` (95 sites) | new | a headless test runs the command set with stdout captured and asserts it stays empty |
| 0.3 | `input()` → injected `confirm: Callable[[str], bool]`; CLI supplies the prompt, everything else non-interactive | 2.1 | headless suite already fails fast on stdin; add a test that `raman_mode` twice does not prompt |
| 0.4 | EventBus; remove PyQt5 from `acqcontrol`, `pixiscam`, `laser_detection`, `logging_utils`; `QtEventBridge` + `QtLogHandler` move into the GUI package | new | headless suite runs with `sys.modules['PyQt5'] = None` — the proof of headlessness |
| 0.5 | Self-registering `@ui_callable`; delete the 120 dict entries | new | snapshot the current command map into a test *first*, then refactor against it |
| 0.6 | HardwareExecutor; `--simulate` and `--serve` flags replace the cwd heuristic | 1.5 | a test issues a command during a simulated scan and gets `busy`; cancel still works |

Order matters: 0.1 and 0.2 make the console useful, 0.3 makes remote
commands safe, 0.4 is the load-bearing one, 0.5 is what makes new
features one-place, 0.6 makes a second client safe. Roughly one session
each; 0.4 and 0.6 may take two.

### Phase 1 — daemon and API

New package `remote/` (name searchable, not "web" which collides with
the old branch): `server.py` (FastAPI app, uvicorn in a thread),
`schemas.py` (pydantic models for the wire), `auth.py` (token check),
`client.py` (the Python wrapper). `interface_run_me.py --serve` starts it
alongside the CLI; `--serve --no-cli` is the pure daemon. Imports happen
inside the flag branch, so a lab PC without FastAPI still runs the
classic app.

Tests: unit — `TestClient` against a simulate-mode `Interface` for every
endpoint and both auth outcomes; workflow — a headless client connects
over WebSocket and HTTP exactly as the browser will: starts live view,
receives N spectra, runs a two-step scan, watches progress reach 100,
starts another and cancels it, and confirms the log stream carried every
step.

### Phase 2 — browser UI and the diagnostic log

One static page served by the daemon. Vanilla JavaScript, a vendored
`uPlot` for streaming line plots (small, fast, no framework), no Node
toolchain on the lab PC. Panels: status tiles generated from the
snapshot; live spectrum; console with registry-driven `help` and
history; scan parameters generated from the four parameter dicts, as the
Qt tabs already are; scan progress with per-step status; log viewer with
level filter. Read-only until a token is entered.

Alongside it, `DiagnosticLog`: a bus subscriber that writes one JSONL
line per event into the scan's data directory. This is the
active-diagnostics deliverable and it does not need a browser: a six-hour
scan with a blocked laser leaves a timestamped record of when the counts
collapsed and what the motors were doing.

If you would rather write no JavaScript at all, NiceGUI can be mounted
onto the same FastAPI app later and the API stays as it is. I would still
start with the static page: it is replaceable, and the API is the part
that lasts.

### Phase 3 — network and operations

Tailscale on the lab PC and your machines; the daemon binds to the
tailnet address by explicit flag; a short `docs/remote_access.md` for the
student. The daemon is *the application*, not a service that autostarts:
an autostarted daemon owning the COM ports would collide with a student
running the classic command. Revisit once the web path is trusted.

### Phase 4 — optional, later

Move the Qt GUI's own command path onto the executor and its displays
onto the bus, then decide whether it earns its keep once the browser
does the same job. Not required for anything above.

## 6. Open questions

1. How does RDP reach the lab PC today, and can Tailscale be installed
   there?
2. Python version on the lab PC. `requirements.txt` pins numpy 2.3.3,
   which implies 3.11 or newer; FastAPI is fine on anything current.
3. Should remote write access require someone at the bench to arm it?
4. Who else will use the browser view: the student only, or the wider
   group? This decides whether two access levels are enough.

## 7. Effort

Phase 0 six to eight sessions, Phase 1 two to three, Phase 2 three to
four, Phase 3 one plus whatever IT requires. Phase 0 is the bulk and it
is also the modernization backlog you already intended to work through;
the web interface is the forcing function that gives it an order.
