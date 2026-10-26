import json
import threading
import unittest
import urllib.request

from app.main import create_server


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def test_health(self):
        self.assertEqual(self.get("/healthz"), (200, {"status": "ok"}))

    def test_root_identifies_service(self):
        status, body = self.get("/")
        self.assertEqual((status, body["service"]), (200, "orders-api"))


if __name__ == "__main__":
    unittest.main()
