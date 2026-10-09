import sys
import os
import logging
from logging.handlers import RotatingFileHandler


def is_frozen() -> bool:
    return getattr(sys,"frozen",False)


def get_bundle_dir() -> str:
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_app_dir() -> str:
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BUNDLE_DIR = get_bundle_dir()
APP_DIR = get_app_dir()
TEMPLATES_DIR = os.path.join(BUNDLE_DIR, "frontend", "templates")
STATIC_DIR = os.path.join(BUNDLE_DIR, "frontend", "static")
INDEX_HTML = os.path.join(TEMPLATES_DIR, "index.html")
ICON_PATH = os.path.join(BUNDLE_DIR, "assets", "vtb.ico")
BASE_MODEL_PATH = os.path.join(BUNDLE_DIR, "assets", "base_model.txt")
DB_PATH = os.path.join(APP_DIR, "vtb_analytics.db")
UPDATED_MODEL_PATH = os.path.join(APP_DIR, "updated_model.txt")
LOG_PATH = os.path.join(APP_DIR, "vtb_analytics.log")
EXPORT_DIR = os.path.join(APP_DIR, "exports")


os.makedirs(EXPORT_DIR, exist_ok=True)
WINDOW_TITLE = "ВТБ Аналитика — Десктопный Терминал"
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
WINDOW_MIN_SIZE = (1200, 700)


RISK_LOW_THRESHOLD = 0.30    # < 30% — зелёная зона
RISK_HIGH_THRESHOLD = 0.70   # > 70% — красная зона


# ML-параметры 
LGBM_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbosity": -1,
}
FEATURE_COLUMNS = [
    "age",
    "deposit_amount",
    "current_rate",
    "market_rate",
    "rate_diff",
    "login_count",
    "days_to_maturity",
    "days_since_last_login",
    "product_count",
]
SYNTHETIC_ROWS = 3000
SYNTHETIC_CHURN_RATE = 0.15
DEFAULT_PAGE_SIZE = 100
CACHE_TTL_SECONDS = 60


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("vtb_analytics")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


    if not is_frozen():
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    return logger
