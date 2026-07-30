import tempfile
import unittest
from pathlib import Path

from book_assets import generate_book_assets


class GenerateBookAssetsTests(unittest.TestCase):
    def test_generate_book_assets_creates_json_and_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            image_dir = tmp_path / "img" / "테스트 교재"
            image_dir.mkdir(parents=True)
            (image_dir / "001.png").write_bytes(b"fake png")
            (image_dir / "002.jpg").write_bytes(b"fake jpg")

            output_dir = tmp_path / "textbooks"
            html_path, json_path = generate_book_assets(
                folder_name="테스트 교재",
                image_dir=image_dir,
                output_dir=output_dir,
            )

            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("테스트 교재", json_path.read_text(encoding="utf-8"))
            self.assertIn("001.png", json_path.read_text(encoding="utf-8"))

    def test_generate_book_assets_adds_viewer_html_and_index_card(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            image_dir = tmp_path / "img" / "테스트 교재"
            image_dir.mkdir(parents=True)
            (image_dir / "001.png").write_bytes(b"fake png")

            output_dir = tmp_path / "textbooks"
            index_path = tmp_path / "index.html"
            index_path.write_text(
                "<!DOCTYPE html><html><body><div class='card-grid' id='cardGrid'></div></body></html>",
                encoding="utf-8",
            )

            html_path, json_path = generate_book_assets(
                folder_name="테스트 교재",
                image_dir=image_dir,
                output_dir=output_dir,
                index_path=index_path,
            )

            self.assertTrue((output_dir / "viewer.html").exists())
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("001.png", html_text)
            self.assertIn("테스트 교재", html_text)
            self.assertIn("테스트_교재.html", index_path.read_text(encoding="utf-8"))


if __name__ == '__main__':
    unittest.main()
