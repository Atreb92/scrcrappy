# scrcrappy packaging — design

Status: draft for approval, 2026-10-19.

## Intent

Installing scrcrappy should be one command per OS, with as few things to set up by hand as possible.
Today it takes system packages (Go, libusb, GStreamer dev headers), building the patched qvh, creating a
venv, `pip install -e .`, and running from the project folder.

Right now the only user is the author (Fedora daily, macOS too). The repo will be published on GitHub as
open source later, so the install path should already be the one strangers will use.

## Goals

- **macOS:** `brew tap <owner>/scrcrappy` once, then `brew install scrcrappy`, then `scrcrappy`.
- **Linux:** `sudo dnf install pipx`, then one `pipx install …` command, then `scrcrappy`. No Go, no
  compiler, no GStreamer.
- Nobody compiles qvh by hand: the Linux build is prebuilt by CI; Homebrew builds it in the formula.
- The current developer workflow (`.venv`, `pip install -e .`, `scripts/build-qvh.sh`) keeps working.

## Non-goals (for now)

- A rewrite in Go or Rust. Decided: keep the Python app; a single binary may come later for other reasons.
- PyPI publishing (until the repo is public; then `pipx install scrcrappy` is a small follow-up).
- Fedora COPR, Flatpak, Snap, AppImage, Windows, Homebrew on Linux.
- An app-menu / Launchpad icon.

## Anti-goals

- An install that silently needs GStreamer, a Go toolchain or a C compiler on the user's machine.
- An install that downloads code at first run (the qvh binary ships inside the package).
- Breaking `--qvh` or the repo-local `bin/qvh` used during development.

## Decided

1. **qvh without GStreamer.** Add a hunk to `third_party/qvh.patch` that removes qvh's `gstreamer`
   command and its MP3/OGG audio recording (the only users of `screencapture/gstadapter`) and drops that
   import. scrcrappy only runs `qvh record`. Verified 2026-10-19 on the iPhone 8 from Fedora: the patched
   build links only libusb at runtime and streamed 655 frames (750×1334) in 15 s. The removed commands
   should fail with a clear message rather than vanish silently (exact wording: builder's call).
   `scripts/build-qvh.sh` and the README then no longer need GStreamer packages.
2. **qvh ships inside the Python package**, as package data next to the code (e.g. `scrcrappy/bin/qvh`).
   scrcrappy looks for qvh in this order: `--qvh`, the copy in the package, the repo's `bin/qvh`
   (development), then `PATH`.
3. **Linux = a platform wheel installed with pipx.** CI builds qvh for Linux x86_64, puts it in the
   package, builds a wheel tagged for that platform (not `py3-none-any`), and attaches it to a GitHub
   release. Install: `pipx install <release wheel URL>`. Locally, before the repo is public:
   `scripts/build-qvh.sh` then `pipx install .` from the checkout gives the same result.
4. **macOS = a formula in the author's own tap** (`<owner>/homebrew-scrcrappy`). It depends on `libusb`,
   builds qvh from source with Go and `pkg-config` (build-only deps), installs the Python app with its
   dependencies into its own environment, and links one `scrcrappy` command. A personal tap may use the
   prebuilt wheels of pygame-ce / PyAV / numpy (they bundle SDL and FFmpeg); building those from source
   is not required.
5. **Releases come from version tags** (`v0.2.0`, …). The version lives in one place (`pyproject.toml`).
   A tag triggers the CI release build; the formula points at the tag's source tarball.
6. **What can be tested now.** The repo isn't on GitHub yet and no Mac is available (2026-10-19). Build now
   and verify on Fedora: the qvh patch, qvh inside the package, `pipx install .` from the checkout (then
   `scrcrappy` from any folder, video and agent mode working). Write now but mark **untested** in the
   plan and README: the GitHub Actions release workflow, the release wheel, and the Homebrew formula and tap.
   They get tested when the repo is public and a Mac is at hand; macOS as a whole is already untested
   (TODO.md › Verify).
7. **Formula updates are manual** (my call): on each release the author updates `url` and `sha256` in the
   tap, one step documented in the repo. The formula's source of truth is the tap repo; this repo keeps a
   copy under `packaging/` until the tap exists. CI automation of this is a later option.

## Still manual, documented in the README

- Linux: `usbmuxd` (most desktops have it) and `libusb` (almost always present).
- Linux Bluetooth mode only: `python3-dbus` and `python3-gobject` from dnf (the helper runs under the
  system python, as today).
- Jailbreak mode: scrcrappy-agent on the phone (its own repo).

## Left to the builder

- Build hook vs. separate script for putting qvh into the package before `python -m build`.
- The exact wheel platform tag (manylinux level) and how it's applied.
- GitHub Actions workflow layout; whether CI also runs the test suite.
- Formula details (how the Python environment is created, `test do` block).
- README install section wording; keeping it to a few lines per OS.
- arm64 Linux wheel: nice to have, not required.

## Open until the repo is public

- The GitHub owner / repo name used in URLs, the tap name and the formula. Use a placeholder until then.
