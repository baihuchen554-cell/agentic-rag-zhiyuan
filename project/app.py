"""knowva：公开首页与按账号隔离的个人工作空间。"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core.terminal_text import configure_chinese_terminal, configure_quiet_library_logs
if __name__ == "__main__":
    configure_chinese_terminal()
import config
if __name__ == "__main__":
    configure_quiet_library_logs()
from account_server import create_app
app = create_app()
if __name__ == "__main__":
    import uvicorn
    import logging
    log = logging.getLogger('knowva')
    log.setLevel(logging.INFO)
    log.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    log.addHandler(handler)
    print(f"{config.APP_NAME} 正在启动…", flush=True)
    uvicorn.run(app, host=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"),
                port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")
