class MeetilyExporter < Formula
  include Language::Python::Virtualenv

  desc "Export Meetily meetings as markdown"
  homepage "https://github.com/dino-rodriguez/meetily-exporter"
  url "https://github.com/dino-rodriguez/meetily-exporter/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "6b971ba1e9502b54946eae6818fc6b70b5d52a294799f2cf1009b5308ac957dc"
  license "MIT"

  depends_on "python@3.12"

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
