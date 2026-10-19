# Homebrew formula for the OWNER/scrcrappy tap (copy to Formula/scrcrappy.rb there; see docs/releasing.md).
# UNTESTED: written before the repo was on GitHub and without a Mac.
class Scrcrappy < Formula
  include Language::Python::Virtualenv

  desc "Mirror and control an iPhone over USB (scrcpy for iOS)"
  homepage "https://github.com/OWNER/scrcrappy"
  url "https://github.com/OWNER/scrcrappy/archive/refs/tags/v0.2.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  depends_on "go" => :build
  depends_on "pkg-config" => :build
  depends_on "libusb"
  depends_on "python@3.13"

  # Same pin as scripts/build-qvh.sh
  resource "qvh" do
    url "https://github.com/danielpaulus/quicktime_video_hack.git",
        revision: "d81396e2e7758d98c2a594853b64f98b54a8a871"
  end

  def install
    resource("qvh").stage buildpath/"qvh-src"
    system "sh", "scripts/build-qvh.sh", buildpath/"qvh-src" # patched, no GStreamer -> scrcrappy/bin/qvh

    # Personal tap: dependencies come as PyPI wheels (pygame-ce bundles SDL, av bundles FFmpeg). virtualenv_create
    # points the venv at python@3.13's opt path, so it survives Python patch upgrades; pip_install isn't used
    # because it forces building every dependency from source.
    virtualenv_create(libexec, "python3.13", without_pip: false)
    system libexec/"bin/pip", "install", buildpath
    bin.install_symlink libexec/"bin/scrcrappy"
  end

  test do
    assert_match "usage: scrcrappy", shell_output("#{bin}/scrcrappy --help")
  end
end
