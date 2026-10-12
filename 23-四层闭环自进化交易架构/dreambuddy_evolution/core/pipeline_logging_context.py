"""PipelineLoggingContext — 日志配置组件

从 evolution_pipeline.py _setup_logging 抽出。
集中日志持久化：FileHandler + RotatingFileHandler，确保运行日志可追溯落盘。
FAIL-OPEN: 日志配置失败不影响主流程。
"""
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


class PipelineLoggingContext:
    """集中日志配置上下文。

    职责：
    - 配置 dreambuddy_evolution 包的集中日志（FileHandler + 控制台）
    - 提供 get_logger 便捷方法

    日志文件: dreambuddy_evolution/logs/evolution_pipeline.log（轮转，单文件 10MB，保留 5 份）
    """

    def __init__(self, log_dir: Path | None = None):
        self._configured = False
        self._log_dir = log_dir or (Path(__file__).resolve().parent.parent / "logs")

    def configure(self) -> None:
        """配置日志（FAIL-OPEN: 失败不阻断）"""
        if self._configured:
            return
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self._log_dir / "evolution_pipeline.log"

            pkg_logger = logging.getLogger("dreambuddy_evolution")
            if not any(isinstance(h, RotatingFileHandler) for h in pkg_logger.handlers):
                fh = RotatingFileHandler(
                    str(log_file), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
                )
                fh.setLevel(logging.INFO)
                fh.setFormatter(
                    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
                )
                pkg_logger.addHandler(fh)
                pkg_logger.setLevel(logging.INFO)
            self._configured = True
        except Exception:  # noqa: BLE001
            pass  # FAIL-OPEN: 日志配置失败不阻断

    def get_logger(self, name: str = "dreambuddy_evolution") -> logging.Logger:
        """获取 logger"""
        return logging.getLogger(name)
