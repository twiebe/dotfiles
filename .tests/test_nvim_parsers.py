"""Tests for nvim/.local/bin/nvim-parsers.

The script installs a prebuilt parser tarball into ~/.local/share/nvim/site.
Each test runs it against a temporary HOME; the download path is covered with
a fake `curl` on PATH that records the URL and hands back a fixture tarball,
so nothing here touches the network.
"""

import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "nvim" / ".local" / "bin" / "nvim-parsers"
COMMIT = "de9f0f3dbdab1952f136dc7bd67ff3bafdf994da"


def write_lock(home, commit=COMMIT):
    config = home / ".config" / "nvim"
    config.mkdir(parents=True)
    (config / "lazy-lock.json").write_text(
        "{\n"
        '  "nvim-treesitter": { "branch": "main", "commit": "%s" },\n'
        '  "nvim-treesitter-textobjects": { "branch": "main", "commit": "0000000" }\n'
        "}\n" % commit
    )


def write_tarball(path, commit=COMMIT):
    with tempfile.TemporaryDirectory() as src:
        src = Path(src)
        (src / "parser").mkdir()
        (src / "parser" / "lua.so").write_bytes(b"\x7fELF")
        (src / "queries" / "lua").mkdir(parents=True)
        (src / "queries" / "lua" / "highlights.scm").write_text("(comment) @comment\n")
        (src / ".nvim-parsers").write_text(commit + "\n")
        with tarfile.open(path, "w:gz") as tar:
            for name in ("parser", "queries", ".nvim-parsers"):
                tar.add(src / name, arcname=name)


class NvimParsersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.site = self.home / ".local" / "share" / "nvim" / "site"
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
        }
        return subprocess.run(
            [str(SCRIPT), *args], env=env, capture_output=True, text=True
        )

    def fake_curl(self, tarball):
        # Records the URL and writes the fixture to the -o target.
        (self.bin / "curl").write_text(
            "#!/bin/sh\n"
            f'echo "$@" > "{self.tmp.name}/curl.args"\n'
            'while [ $# -gt 1 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
            f'cp "{tarball}" "$out"\n'
        )
        (self.bin / "curl").chmod(0o755)

    def test_from_installs_tarball(self):
        write_lock(self.home)
        tarball = Path(self.tmp.name) / "p.tar.gz"
        write_tarball(tarball)

        result = self.run_script("--from", str(tarball))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.site / "parser" / "lua.so").exists())
        self.assertTrue((self.site / "queries" / "lua" / "highlights.scm").exists())
        self.assertEqual((self.site / ".nvim-parsers").read_text().strip(), COMMIT)

    def test_install_removes_previous_parsers_and_queries(self):
        write_lock(self.home)
        (self.site / "parser").mkdir(parents=True)
        (self.site / "parser" / "old.so").write_bytes(b"")
        (self.site / "queries" / "old").mkdir(parents=True)
        tarball = Path(self.tmp.name) / "p.tar.gz"
        write_tarball(tarball)

        result = self.run_script("--from", str(tarball))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "parser" / "old.so").exists())
        self.assertFalse((self.site / "queries" / "old").exists())
        self.assertTrue((self.site / "parser" / "lua.so").exists())

    def test_downloads_release_matching_lock_commit(self):
        write_lock(self.home)
        tarball = Path(self.tmp.name) / "p.tar.gz"
        write_tarball(tarball)
        self.fake_curl(tarball)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        url = Path(self.tmp.name, "curl.args").read_text()
        self.assertIn(
            "https://github.com/twiebe/dotfiles/releases/download/nvim-parsers-de9f0f3/nvim-parsers-",
            url,
        )
        self.assertIn(".tar.gz", url)
        self.assertTrue((self.site / "parser" / "lua.so").exists())

    def test_up_to_date_stamp_skips_download(self):
        write_lock(self.home)
        self.site.mkdir(parents=True)
        (self.site / ".nvim-parsers").write_text(COMMIT + "\n")
        # No fake curl on PATH: a download attempt would hit the network.
        (self.bin / "curl").write_text("#!/bin/sh\nexit 99\n")
        (self.bin / "curl").chmod(0o755)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("up to date", result.stdout)

    def test_stale_stamp_triggers_download(self):
        write_lock(self.home)
        self.site.mkdir(parents=True)
        (self.site / ".nvim-parsers").write_text("0123456789abcdef\n")
        tarball = Path(self.tmp.name) / "p.tar.gz"
        write_tarball(tarball)
        self.fake_curl(tarball)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / ".nvim-parsers").read_text().strip(), COMMIT)

    def test_lock_without_treesitter_fails(self):
        config = self.home / ".config" / "nvim"
        config.mkdir(parents=True)
        (config / "lazy-lock.json").write_text("{}\n")

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nvim-treesitter", result.stderr)


if __name__ == "__main__":
    unittest.main()
