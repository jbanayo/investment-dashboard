import re
import tempfile
import unittest
from pathlib import Path

from portfolio import create_app


class TourTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "portfolio.db"
        self.client = create_app({"TESTING": True, "DATABASE": str(database)}).test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tour_starts_once_then_stays_available_from_the_nav(self):
        first = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn('data-tour-autostart="1"', first)
        self.assertIn("data-tour-start", first)

        self.assertEqual(204, self.client.post("/tour/seen").status_code)

        later = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn('data-tour-autostart="0"', later)
        self.assertIn("data-tour-start", later)

    def test_every_step_in_tour_js_has_its_anchor_on_its_page(self):
        script = (Path(__file__).parent.parent / "portfolio/static/tour.js").read_text()
        steps = re.findall(r'path: "([^"]+)", target: "([^"]+)"', script)
        self.assertGreater(len(steps), 5)
        for path, target in steps:
            page = self.client.get(path).get_data(as_text=True)
            self.assertIn(f'data-tour="{target}"', page, f"{path} is missing the {target} anchor")

if __name__ == "__main__":
    unittest.main()
