class Recap < Formula
  include Language::Python::Virtualenv

  desc "Export Meetily meetings as markdown"
  homepage "https://github.com/anthropics/recap"
  url "https://github.com/anthropics/recap/archive/refs/tags/v0.1.0.tar.gz"
  sha256 ""
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  service do
    run [opt_bin/"recap", "watch"]
    keep_alive true
    log_path var/"log/recap.log"
    error_log_path var/"log/recap.log"
  end

  test do
    system bin/"recap", "--help"
  end
end
