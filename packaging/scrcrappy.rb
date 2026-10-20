# Homebrew formula for the atreb92/scrcrappy tap (copy to Formula/scrcrappy.rb there; see docs/releasing.md).
# UNTESTED: written before the repo was on GitHub and without a Mac. Linux (Linuxbrew) is meant to work too; usbmuxd comes from the distro.
class Scrcrappy < Formula
  desc "Mirror and control an iPhone over USB (scrcpy for iOS)"
  homepage "https://github.com/atreb92/scrcrappy"
  url "https://github.com/atreb92/scrcrappy/archive/refs/tags/v0.2.0.tar.gz"
  sha256 "7cf05a47bc46a8913c0d1f91a7bca8caa3cb6a6a59c27bda5891687a5ef6154e"
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

    # Personal tap: dependencies come as PyPI wheels (pygame-ce bundles SDL, av bundles FFmpeg). A plain venv from
    # python@3.13's opt path survives Python patch upgrades; Homebrew's virtualenv_create makes it without pip, and
    # pip_install forces building every dependency from source.
    system Formula["python@3.13"].opt_bin/"python3.13", "-m", "venv", libexec
    system libexec/"bin/pip", "install", buildpath
    bin.install_symlink libexec/"bin/scrcrappy"
  end

  test do
    assert_match "usage: scrcrappy", shell_output("#{bin}/scrcrappy --help")
  end
end
