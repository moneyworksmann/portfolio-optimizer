import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "portfolio-intelligence"))

from app import app  # noqa: E402
