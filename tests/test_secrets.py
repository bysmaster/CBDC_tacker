import re
import unittest
from pathlib import Path


class TestSecretsLeak(unittest.TestCase):
    def test_no_hardcoded_api_keys(self):
        root = Path(__file__).resolve().parents[1]
        patterns = [
            re.compile(r"Aiza[0-9A-Za-z\-_]{20,}"),
            re.compile(r"AiZa[0-9A-Za-z\-_]{20,}"),
            re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
            re.compile(r"sk-[0-9A-Za-z]{10,}"),
        ]

        ignore_dirs = {".git", "__pycache__", ".venv", "venv", ".trae", ".idea"}
        ignore_ext = {".docx", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"}

        hits = []
        for path in root.rglob("*"):
            if any(part in ignore_dirs for part in path.parts):
                continue
            if path.is_dir():
                continue
            if path.suffix.lower() in ignore_ext:
                continue
            if path.name in {".env", ".env.example"}:
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for pat in patterns:
                m = pat.search(text)
                if m:
                    hits.append(f"{path}: {m.group(0)[:8]}***")

        self.assertEqual(hits, [], "Found potential hardcoded secrets:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
