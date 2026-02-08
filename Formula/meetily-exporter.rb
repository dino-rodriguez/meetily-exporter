class MeetilyExporter < Formula
  include Language::Python::Virtualenv

  desc "Export Meetily meetings as markdown"
  homepage "https://github.com/dino-rodriguez/meetily-exporter"
  url "https://github.com/dino-rodriguez/meetily-exporter/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "c072517a318a4f098357e1b280fa97675035cf96aae6d465086c5d790eb7e8b2"
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
