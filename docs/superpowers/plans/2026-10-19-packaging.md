# Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pipx install` on Linux and a Homebrew tap on macOS install a working `scrcrappy` command, with the patched qvh inside and no GStreamer anywhere.

**Architecture:** The patched qvh drops its GStreamer commands. `scripts/build-qvh.sh` writes it into the Python package (`scrcrappy/bin/qvh`), which setuptools ships as package data. A GitHub Actions tag build makes a Linux platform wheel; a formula in a tap builds qvh from a pinned source and pip-installs the app.

**Tech Stack:** Python 3.11+, setuptools, pipx, Go (cgo + libusb), GitHub Actions, Homebrew.

**Spec:** `docs/superpowers/specs/2026-10-19-packaging-design.md`

## Global Constraints

- qvh links only libusb at runtime (no GStreamer, no GLib).
- qvh lookup order: `--qvh`, the package copy `scrcrappy/bin/qvh`, the repo's `bin/qvh`, then `PATH`.
- The version lives only in `pyproject.toml`; tags are `v<version>`.
- Release workflow, release wheel, Homebrew formula: written now, marked **untested** in README and docs.
- Formula updates are manual per release; the formula's copy lives in `packaging/scrcrappy.rb` until the tap exists.
- GitHub owner placeholder: `OWNER` (the repo isn't public yet).
- `pip install -e .` + `.venv` development keeps working.

## Review Focus

- A wheel or pipx install that loses qvh's executable bit → scrcrappy must still run it (Task 2 test).
- `scrcrappy` started from a folder other than the checkout → still finds the packaged qvh (Task 2 test).
- An old GStreamer-linked `bin/qvh` left in the repo → the package copy wins (Task 2 test).
- `pipx install .` done before building qvh → a clear error naming `scripts/build-qvh.sh` (Task 2 test).
- The removed qvh commands → exit non-zero with a message, not a crash or silent success (Task 1 check).

---

### Task 1: qvh without GStreamer, built into the package

**Files:**
- Modify: `third_party/qvh.patch` (add a `main.go` hunk)
- Modify: `scripts/build-qvh.sh`
- Modify: `README.md` (Setup: drop GStreamer packages)

**Interfaces:**
- Produces: `scripts/build-qvh.sh [SRC_DIR]` — with no argument clones qvh at the pinned commit; with an argument uses that checkout (Homebrew passes its staged resource). Applies the patch, writes `scrcrappy/bin/qvh`.

- [ ] **Step 1:** In `main.go` (pinned commit `d81396e`): remove the `screencapture/gstadapter` import; replace the bodies of `recordAudioGst`, `startGStreamerWithCustomPipeline`, `startGStreamer` with `log.Fatal("scrcrappy: qvh is built without GStreamer; use qvh record")`; replace `gstadapter.OGG` / `gstadapter.MP3` with `"ogg"` / `"mp3"`. Regenerate `third_party/qvh.patch` from the edited checkout (`git diff`), keeping the two existing hunks.
- [ ] **Step 2:** `build-qvh.sh`: optional `$1` source dir (skip clone/checkout when given); output `$ROOT/scrcrappy/bin/qvh`; header comment needs only go + libusb (+ pkg-config).
- [ ] **Step 3: Verify** — `sh scripts/build-qvh.sh` then `ldd scrcrappy/bin/qvh | grep -c gst` → `0`; `scrcrappy/bin/qvh gstreamer; echo $?` → message printed, exit status non-zero.
- [ ] **Step 4:** README Setup: Fedora `sudo dnf install golang libusb1-devel`, macOS `brew install go libusb pkg-config`.
- [ ] **Step 5: Commit** `build: qvh without GStreamer, built into the package`

### Task 2: Ship qvh in the package and find it

**Files:**
- Modify: `pyproject.toml` (package-data `bin/qvh`; version `0.2.0`)
- Modify: `scrcrappy/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `find_qvh(flag: str | None, package: Path = PACKAGED_QVH, repo: Path = REPO_QVH) -> str | None` in `scrcrappy/__main__.py`; `PACKAGED_QVH = Path(__file__).parent / "bin" / "qvh"`, `REPO_QVH = <repo>/bin/qvh`. `--qvh` default becomes `None`. If the chosen file exists but isn't executable, `find_qvh` sets the user's exec bit and returns it.

- [ ] **Step 1: Write the failing tests**

```python
def test_find_qvh_prefers_flag_then_package_then_repo(tmp_path):
    pkg, repo = tmp_path / "pkg" / "qvh", tmp_path / "repo" / "qvh"
    for p in (pkg, repo):
        p.parent.mkdir(); p.write_text(""); p.chmod(0o755)
    assert cli.find_qvh("/bin/true", pkg, repo) == "/bin/true"
    assert cli.find_qvh(None, pkg, repo) == str(pkg)          # package beats an old repo build
    pkg.unlink()
    assert cli.find_qvh(None, pkg, repo) == str(repo)

def test_find_qvh_restores_exec_bit(tmp_path):
    pkg = tmp_path / "qvh"; pkg.write_text(""); pkg.chmod(0o644)
    assert cli.find_qvh(None, pkg, tmp_path / "none") == str(pkg)
    assert os.access(pkg, os.X_OK)

def test_missing_qvh_names_build_script(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "PACKAGED_QVH", tmp_path / "a"); monkeypatch.setattr(cli, "REPO_QVH", tmp_path / "b")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli.main([]) == 1
    assert "scripts/build-qvh.sh" in capsys.readouterr().err
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_main.py -q` → the three new tests FAIL (`find_qvh` not defined).
- [ ] **Step 3:** Implement `find_qvh`, use it in `main()`; fix `test_missing_qvh_exits_1` if its message changes. `pyproject.toml`: `[tool.setuptools.package-data] scrcrappy = ["icons/*", "bin/qvh"]`, version `0.2.0`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` → all pass.
- [ ] **Step 5: Verify the install** — `pipx install --force .` from the checkout; from `/tmp`: `scrcrappy --help` works and `ls -l ~/.local/share/pipx/venvs/scrcrappy/lib/python*/site-packages/scrcrappy/bin/qvh` shows `x` bits. Manual (user, phone attached): `scrcrappy --mouse agent` from any folder shows video and takes clicks.
- [ ] **Step 6: Commit** `build: ship qvh inside the package; pipx install works`

### Task 3: Release build (untested until the repo is on GitHub)

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `docs/releasing.md`

- [ ] **Step 1:** Workflow on `push: tags: ["v*"]`, runner `ubuntu-22.04`: checkout; fail unless the tag equals `v` + `pyproject.toml` version; `actions/setup-go`; `apt-get install libusb-1.0-0-dev pkg-config`; `sh scripts/build-qvh.sh`; `pip install build wheel pytest . && SDL_VIDEODRIVER=dummy pytest -q`; `python -m build --wheel`; `python -m wheel tags --python-tag py3 --abi-tag none --platform-tag manylinux_2_35_x86_64 --remove dist/*.whl`; `gh release create "$TAG" dist/*.whl` with `GITHUB_TOKEN`.
- [ ] **Step 2:** `docs/releasing.md`: bump version → commit → tag `v<version>` → push tag → CI attaches the wheel → update `url` + `sha256` in the formula (`curl -L <tarball> | shasum -a 256`) in `packaging/scrcrappy.rb` and the tap. Says the workflow is untested.
- [ ] **Step 3: Verify** locally what can be: `python -m build --wheel` + the `wheel tags` command produce `scrcrappy-0.2.0-py3-none-manylinux_2_35_x86_64.whl` containing `scrcrappy/bin/qvh` (`unzip -l`); `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"` parses.
- [ ] **Step 4: Commit** `ci: release workflow building the Linux wheel (untested)`

### Task 4: Homebrew formula and install docs (untested until public + a Mac)

**Files:**
- Create: `packaging/scrcrappy.rb`
- Modify: `README.md` (Install section first, per OS)

- [ ] **Step 1:** Formula: `desc "scrcpy for iOS: mirror and control an iPhone over USB"`, `homepage`/`url` on `OWNER`, `version` via tag tarball, `sha256` placeholder; `depends_on "go" => :build`, `"pkg-config" => :build`, `"libusb"`, `"python@3.13"`; `resource "qvh"` = git `https://github.com/danielpaulus/quicktime_video_hack.git`, `revision: "d81396e2e7758d98c2a594853b64f98b54a8a871"`. `install`: stage the resource, `system "sh", "scripts/build-qvh.sh", <staged dir>`; `virtualenv_create(libexec, "python3.13")`; pip-install `buildpath` (dependencies as wheels from PyPI); `bin.install_symlink libexec/"bin/scrcrappy"`. `test do`: `scrcrappy --help`. Header comment: untested.
- [ ] **Step 2:** README: an **Install** section above Setup — macOS `brew tap OWNER/scrcrappy && brew install scrcrappy` (untested); Linux `sudo dnf install pipx` + `pipx install <release wheel URL>` (or `pipx install .` from a checkout after `scripts/build-qvh.sh`); still manual: usbmuxd, Bluetooth-mode python3-dbus / python3-gobject. Rename the existing Setup to "Development".
- [ ] **Step 3: Verify** `ruby -c packaging/scrcrappy.rb` → `Syntax OK` (if ruby is installed).
- [ ] **Step 4: Commit** `packaging: Homebrew formula (untested) and install docs`; tick TODO.md items; add "Test brew formula + release workflow once public, on a Mac".
