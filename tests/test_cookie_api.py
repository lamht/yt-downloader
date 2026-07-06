import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_index_page_contains_youtube_login_helper():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert b"Login YouTube" in response.content


class CookieApiTests(unittest.TestCase):
    def test_update_cookie_endpoint_writes_cookie_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_path = Path(tmpdir) / "cookies.txt"
            os.chdir(tmpdir)

            with TestClient(app) as client:
                response = client.post("/cookie", json={"content": "# Netscape HTTP Cookie File"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(cookie_path.read_text(encoding="utf-8"), "# Netscape HTTP Cookie File")

    def test_cookie_status_reports_local_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            with TestClient(app) as client:
                response = client.get("/cookie/status")

            self.assertEqual(response.status_code, 200)
            self.assertIn("cookies.txt", response.json()["path"])


if __name__ == "__main__":
    unittest.main()
