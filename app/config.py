import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{DATA_DIR / 'dev.sqlite'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
