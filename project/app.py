import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.terminal_text import configure_chinese_terminal, configure_quiet_library_logs

if __name__ == "__main__":
    configure_chinese_terminal()
    configure_quiet_library_logs()

import config

if __name__ == "__main__":
    try:
        config.validate_model_api_settings()
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

from ui.css import custom_css, app_theme
from ui.gradio_app import create_gradio_ui
from ui.translations import chinese_i18n, chinese_ui_js, chinese_page_head
from ui.interactions import app_ui_js
from db.vector_db_manager import KnowledgeBaseInUseError

if __name__ == "__main__":
    print("正在初始化，请稍候…", flush=True)
    try:
        demo = create_gradio_ui()
    except KnowledgeBaseInUseError as exc:
        print(str(exc))
        sys.exit(1)
    demo.launch(css=custom_css, theme=app_theme, i18n=chinese_i18n,
                head=chinese_page_head, js=chinese_ui_js + app_ui_js,
                favicon_path=os.path.join(config.ASSETS_DIR, "logo.png"))
