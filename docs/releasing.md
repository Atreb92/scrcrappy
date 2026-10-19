# Releasing

> The release workflow and the Homebrew formula are **untested**: they were written before the repo was
> on GitHub and without a Mac. Expect to fix small things on the first real release.

1. Bump `version` in `pyproject.toml` (the only place it lives) and commit.
2. Tag and push: `git tag v<version> && git push origin v<version>`.
3. `.github/workflows/release.yml` builds qvh, runs the tests, builds the Linux wheel
   (`scrcrappy-<version>-py3-none-manylinux_2_35_x86_64.whl`, qvh inside) and attaches it to the
   GitHub release. Linux users install it with `pipx install <wheel URL>`.
4. Update the Homebrew formula by hand: in `packaging/scrcrappy.rb` set `url` to the tag's source tarball
   and `sha256` to

   ```sh
   curl -sL https://github.com/OWNER/scrcrappy/archive/refs/tags/v<version>.tar.gz | sha256sum
   ```

   then copy the file to the tap repo (`OWNER/homebrew-scrcrappy`, `Formula/scrcrappy.rb`) and push.
   Check on a Mac: `brew update && brew upgrade scrcrappy && scrcrappy --help`.
5. If qvh's pinned commit changes, update `COMMIT` in `scripts/build-qvh.sh` and the `qvh` resource's
   `revision` in the formula together.
