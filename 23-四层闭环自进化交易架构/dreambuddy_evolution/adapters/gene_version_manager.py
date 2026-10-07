"""
gene_version_manager — 基因库版本控制（快照+回滚）

设计目标:
  1. 新基因写入前自动快照当前基因库
  2. 表现变差时一键回滚到上一版本
  3. 版本元数据可追溯（时间戳/触发源/基因数）

存储结构:
  gene_data/strategy_genes/
    conditions/        # 当前基因库
    actions/
    library.json
    versions/
      v20261007_120000/
        manifest.json  # {version_id, timestamp, n_genes, trigger_source, note}
        conditions/    # 快照备份
        actions/
        library.json
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GeneVersionManager:
    """基因库版本管理器"""

    def __init__(self, strategy_genes_dir: str | Path):
        self._dir = Path(strategy_genes_dir)
        self._versions_dir = self._dir / "versions"

    def snapshot(self, trigger_source: str = "auto", note: str = "") -> Optional[str]:
        """快照当前基因库.

        Returns:
            version_id 或 None（失败时）
        """
        try:
            import uuid
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            version_id = f"v{timestamp}_{uuid.uuid4().hex[:6]}"
            snap_dir = self._versions_dir / version_id
            snap_dir.mkdir(parents=True, exist_ok=True)

            n_genes = 0
            for subdir in ["conditions", "actions"]:
                src = self._dir / subdir
                dst = snap_dir / subdir
                if src.exists():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    n_genes += len(list(dst.glob("*.json")))

            lib_file = self._dir / "library.json"
            if lib_file.exists():
                shutil.copy2(lib_file, snap_dir / "library.json")

            manifest = {
                "version_id": version_id,
                "timestamp": timestamp,
                "n_genes": n_genes,
                "trigger_source": trigger_source,
                "note": note,
            }
            (snap_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"[GeneVersion] 快照 {version_id}: {n_genes} 个基因, 来源={trigger_source}")
            return version_id
        except Exception as e:
            logger.warning(f"[GeneVersion] 快照失败: {e}")
            return None

    def rollback(self, version_id: str) -> bool:
        """回滚到指定版本.

        Returns:
            True 表示回滚成功
        """
        try:
            snap_dir = self._versions_dir / version_id
            if not snap_dir.exists():
                logger.warning(f"[GeneVersion] 版本不存在: {version_id}")
                return False

            # 先快照当前状态（防止回滚失误）
            self.snapshot(trigger_source="pre_rollback", note=f"rollback to {version_id}")

            # 恢复 conditions（先清空当前目录，删除快照后新增的文件）
            for subdir in ["conditions", "actions"]:
                src = snap_dir / subdir
                dst = self._dir / subdir
                if dst.exists():
                    shutil.rmtree(dst)
                if src.exists():
                    shutil.copytree(src, dst)
                else:
                    dst.mkdir(parents=True, exist_ok=True)

            # 恢复 library.json
            lib_src = snap_dir / "library.json"
            lib_dst = self._dir / "library.json"
            if lib_src.exists():
                shutil.copy2(lib_src, lib_dst)

            logger.info(f"[GeneVersion] 回滚到 {version_id} 成功")
            return True
        except Exception as e:
            logger.warning(f"[GeneVersion] 回滚失败: {e}")
            return False

    def list_versions(self) -> list[dict[str, Any]]:
        """列出所有版本（按时间倒序）."""
        versions = []
        if not self._versions_dir.exists():
            return versions
        for snap_dir in sorted(self._versions_dir.iterdir(), reverse=True):
            manifest_file = snap_dir / "manifest.json"
            if manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    versions.append(manifest)
                except Exception:
                    pass
        return versions

    def get_latest_version(self) -> Optional[str]:
        """获取最新版本号."""
        versions = self.list_versions()
        return versions[0]["version_id"] if versions else None
