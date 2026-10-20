# Releasing

> The release workflow and the Linux wheel are proven (v0.2.0), and the Homebrew formula installs on Linuxbrew.
> macOS is still untested.

1. Bump `version` in `pyproject.toml` (the only place it lives) and commit.
2. Tag and push: `git tag v<version> && git push origin v<version>`.
3. `.github/workflows/release.yml` builds qvh, runs the tests, builds the Linux wheel
   (`scrcrappy-<version>-py3-none-manylinux_2_35_x86_64.whl`, qvh inside) and attaches it to the
   GitHub release. Linux users install it with `pipx install <wheel URL>`.
4. The `homebrew` job in the workflow rewrites `url` and `sha256` in `packaging/scrcrappy.rb` and pushes it to the tap
   repo (`atreb92/homebrew-scrcrappy`, `Formula/scrcrappy.rb`). It needs the repo secret `TAP_TOKEN`, a token with write
   access to the tap. Untested: check the first run. By hand, set `url` and `sha256` (`curl -sL <tarball URL> | sha256sum`)
   and copy the file to the tap. Check on a Mac: `brew update && brew upgrade scrcrappy && scrcrappy --help`.
5. If qvh's pinned commit changes, update `COMMIT` in `scripts/build-qvh.sh` and the `qvh` resource's
   `revision` in the formula together.
