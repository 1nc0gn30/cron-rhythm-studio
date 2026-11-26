import importlib
import unittest

MODS = ["cron_rhythm_studio.cli"]


class TestOriginAndHostGuard(unittest.TestCase):
    def test_exact_port_local_origins_allowed(self):
        for name in MODS:
            m = importlib.import_module(name)
            for o in (
                None,
                "",
                "http://localhost:5174",
                "http://127.0.0.1:5174",
                "http://[::1]:5174",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ):
                self.assertTrue(m._is_local_origin(o), (name, o))

    def test_foreign_and_spoofed_port_origins_blocked(self):
        for name in MODS:
            m = importlib.import_module(name)
            for o in (
                "https://evil.example",
                "http://localhost.evil.example:5174",
                "http://127.0.0.1:51740",
                "http://localhost:30000",
                "http://127.0.0.1:8080",
                "https://localhost",
                "null",
                "file://",
                "http://192.168.1.5:5174",
            ):
                self.assertFalse(m._is_local_origin(o), (name, o))

    def test_host_allowlist(self):
        m = importlib.import_module("cron_rhythm_studio.cli")
        for ok in ("127.0.0.1:5174", "localhost:5174", "[::1]:5174", "127.0.0.1", "localhost"):
            self.assertTrue(m._is_allowed_host(ok), ok)
        for bad in ("evil.example.invalid", "evil.example.invalid:5174", "127.0.0.1.evil.com:5174", "127.0.0.1:99999", "192.168.1.1:5174"):
            self.assertFalse(m._is_allowed_host(bad), bad)


if __name__ == "__main__":
    unittest.main()
