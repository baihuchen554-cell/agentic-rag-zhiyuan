"""文档入库的阶段状态；不推算未知工作的百分比。"""

from html import escape
from time import time
from core.document_manager import DocumentProgress


STAGES = (("parsing", "解析文档"), ("chunking", "文本切分"), ("indexing", "建立索引"))


def render_upload_progress(progress: DocumentProgress, started_at=None):
    stage = progress.stage
    finished = stage == "complete"
    failed = finished and progress.failed > 0
    titles = {
        "ready": "文件已上传，等待入库", "preparing": "准备入库…",
        "parsing": "正在解析文档", "chunking": "正在切分文本",
        "indexing": "正在建立索引", "file_done": "当前文档已入库",
        "skipped": "同名文档已存在，已跳过", "failed": "当前文档未完成",
    }
    title = ("部分文档未完成" if progress.added else "入库未完成") if failed else (
        "入库完成" if finished and progress.added else "文档已存在，无需重复入库"
        if finished else titles.get(stage, "准备入库…"))
    state = "error" if failed else "done" if finished else "ready" if stage == "ready" else "busy"
    file_text = (f"第 {progress.file_index} / {progress.total_files} 个文档 · {progress.filename}"
                 if progress.filename else f"共 {progress.total_files} 个文档")
    detail = {
        "ready": "点击“开始入库”，完成后即可提问。",
        "preparing": "文件已上传，正在准备处理。",
        "parsing": "提取正文与表格，文件较大时请稍候。",
        "chunking": "将正文整理为可检索的文本段。",
        "indexing": f"已写入 {progress.completed_chunks} / {progress.total_chunks} 段文本",
        "file_done": "正在处理剩余文档…",
        "skipped": "保留已有文档，继续处理剩余文件。",
        "failed": "正在检查剩余文件…",
    }.get(stage, "")
    if finished:
        file_text = f"共 {progress.total_files} 个文档"
        detail = f"新增 {progress.added} 个"
        if progress.skipped:
            detail += f" · 已存在 {progress.skipped} 个"
        if progress.failed:
            detail += f" · 未完成 {progress.failed} 个，可重试"

    current = next((i for i, item in enumerate(STAGES) if item[0] == stage), -1)
    steps = []
    for index, (_, label) in enumerate(STAGES):
        done = (finished and not failed) or stage == "file_done" or index < current
        active = index == current and not finished
        style = "done" if done else "active" if active else "pending"
        steps.append(f'<li class="{style}"><span class="upload-step-dot">{"✓" if done else index + 1}</span>{label}</li>')

    # 只对已完成写入的文本段显示定量进度；解析阶段保持不定量状态。
    meter = ""
    if stage == "indexing" and progress.total_chunks:
        count, total = progress.completed_chunks, progress.total_chunks
        meter = (f'<div class="upload-meter" role="progressbar" aria-label="已写入文本段" '
                 f'aria-valuemin="0" aria-valuemax="{total}" aria-valuenow="{count}">'
                 f'<span style="width:{count / total * 100:.2f}%"></span></div>')
    elif not finished and stage != "ready":
        meter = '<div class="upload-meter indeterminate" role="progressbar" aria-label="正在处理"><span></span></div>'
    seconds = max(0, int(time() - started_at)) if started_at else 0
    elapsed = f"{seconds} 秒" if seconds < 60 else f"{seconds // 60} 分 {seconds % 60} 秒"
    timer = (f'<span class="upload-elapsed" data-upload-start="{started_at}">已用时 {elapsed}</span>'
             if started_at and not finished else "")
    issues = "".join(f"<li>{escape(issue)}</li>" for issue in progress.issues)
    issues = f'<ul class="upload-issues">{issues}</ul>' if finished and issues else ""
    stepper = "" if failed else f'<ol class="upload-steps">{"".join(steps)}</ol>'
    return (f'<section class="upload-status" data-state="{state}" aria-label="文档入库进度">'
            f'<div class="upload-status-top"><strong>{title}</strong>{timer}</div>'
            f'<p class="upload-filename" title="{escape(file_text, quote=True)}">{escape(file_text)}</p>'
            f'{stepper}{meter}'
            f'<p class="upload-detail" role="status">{escape(detail)}</p>{issues}</section>')
