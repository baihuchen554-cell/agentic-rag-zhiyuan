"""翻译已知的第三方终端提示，保留警告、进度、地址及原始异常信息。"""

import os
import sys


def translate_terminal_text(text: str) -> str:
    prefix_length = len(text) - len(text.lstrip("\r\n"))
    prefix, body = text[:prefix_length], text[prefix_length:]
    warning = (
        "You are sending unauthenticated requests to the HF Hub. "
        "Please set a HF_TOKEN to enable higher rate limits and faster downloads."
    )
    if body.startswith(("Warning: " + warning, warning)):
        body = body.replace(
            warning,
            "当前正在以未认证方式访问 Hugging Face 模型仓库。"
            "设置 HF_TOKEN 可提高请求限额并加快下载速度。",
            1,
        )
        if body.startswith("Warning: "):
            body = "警告：" + body[len("Warning: "):]
    elif body.startswith("Loading weights:"):
        body = body.replace("Loading weights:", "正在加载模型权重：", 1)
        body = body.replace("it/s", "项/秒").replace("s/it", "秒/项")
    elif body.startswith("* Running on local URL:"):
        body = body.replace("* Running on local URL:", "* 本地访问地址：", 1)
        body = body.replace(", with SSR ⚡ (dev mode)", "，已启用服务端渲染 ⚡（开发模式）")
        body = body.replace(", with SSR ⚡ (Node proxy -> Python :", "，已启用服务端渲染 ⚡（Node 代理 → Python 端口：")
        if "（Node 代理" in body:
            body = body.replace(")", "）")
    elif body.startswith("* To create a public link, set `share=True` in `launch()`."):
        body = body.replace(
            "* To create a public link, set `share=True` in `launch()`.",
            "* 如需创建公网访问链接，请在 launch() 中设置 share=True。",
            1,
        )
    elif body.startswith("* Running on public URL:"):
        body = body.replace("* Running on public URL:", "* 公网访问地址：", 1)
    elif body.startswith("Closing server running on port:"):
        body = body.replace("Closing server running on port:", "正在关闭服务，端口：", 1)
    elif body.startswith("Keyboard interruption in main thread... closing server."):
        body = body.replace(
            "Keyboard interruption in main thread... closing server.",
            "收到键盘中断，正在关闭服务。",
            1,
        )
    return prefix + body


class _ChineseTerminalStream:
    """仅转换显示文本；转发刷新、编码、终端检测等操作。"""

    def __init__(self, stream):
        self._stream = stream
        self._skip_newline = False

    def write(self, text):
        if text.startswith("* To create a public link, set `share=True` in `launch()`."):
            self._skip_newline = not text.endswith("\n")
            return len(text)
        if self._skip_newline:
            self._skip_newline = False
            if text == "\n":
                return len(text)
        self._stream.write(translate_terminal_text(text))
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def configure_chinese_terminal():
    """在导入第三方库前调用，让日志处理器及进度条使用中文显示流。"""
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["HF_HUB_VERBOSITY"] = "error"
    os.environ["TQDM_DISABLE"] = "1"
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None and not isinstance(stream, _ChineseTerminalStream):
            setattr(sys, name, _ChineseTerminalStream(stream))


def configure_quiet_library_logs():
    """关闭第三方进度与普通日志，保留错误和异常。"""
    import warnings
    from huggingface_hub.utils import logging as hub_logging
    from loguru import logger

    hub_logging.set_verbosity_error()
    warnings.filterwarnings(
        "ignore",
        message=r"Cannot enable progress bars: environment variable `HF_HUB_DISABLE_PROGRESS_BARS=1` is set and has priority\.",
        category=UserWarning,
        module=r"huggingface_hub\.utils\.tqdm",
    )
    # FastEmbed 使用 Loguru；保留错误，省略下载缓存等非致命提示。
    try:
        logger.remove(0)
    except ValueError:
        pass
    logger.add(sys.stderr, level="ERROR", format="{message}")
