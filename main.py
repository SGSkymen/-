import sys
import os
import ctypes
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import webview  # noqa: E402  (pywebview)
from backend.config import (  # noqa: E402
    INDEX_HTML, ICON_PATH, WINDOW_TITLE, WINDOW_WIDTH, WINDOW_HEIGHT,
    WINDOW_MIN_SIZE, setup_logging, is_frozen,
)
from backend.api import Api  # noqa: E402
logger = setup_logging()


def set_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception as e:
        logger.warning(f"Не удалось установить DPI-awareness: {e}")
        try:
            # Фоллбэк для старых версий Windows (Vista/7)
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def on_closing():
    try:
        api.shutdown()
    except Exception as e:
        logger.warning(f"Ошибка при завершении работы: {e}")


def main():
    set_dpi_awareness()


    global api;api = Api()
    icon_kwargs = {}
    if os.path.exists(ICON_PATH):
        icon_kwargs["icon"] = ICON_PATH
    else:
        logger.warning(f"Иконка не найдена по пути {ICON_PATH} — окно будет без кастомной иконки")

    frontend_root = os.path.dirname(os.path.dirname(INDEX_HTML))

    window = webview.create_window(
        WINDOW_TITLE,
        INDEX_HTML,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=WINDOW_MIN_SIZE,
        confirm_close=True,
        background_color="#0a1128",
    )
    api.set_window(window)
    window.events.closing += on_closing


    gui_backend = "edgechromium" if sys.platform == "win32" else None
    webview.start(gui=gui_backend, debug=not is_frozen())

if __name__ == "__main__":
    main()
