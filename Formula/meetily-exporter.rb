class MeetilyExporter < Formula
  include Language::Python::Virtualenv

  desc "Export Meetily meetings as markdown"
  homepage "https://github.com/dino-rodriguez/meetily-exporter"
  url "https://github.com/dino-rodriguez/meetily-exporter/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "a7f4a6dae0b5ffcf17abbcbd0e7faa9cdfdb33ff85e3976eba5c64e9a1ed8847"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  service do
    run [opt_bin/"meetily-exporter", "watch"]
    keep_alive true
    log_path var/"log/meetily-exporter.log"
    error_log_path var/"log/meetily-exporter.log"
  end

  test do
    system bin/"meetily-exporter", "--help"
  end
end
