"""G0 开工前置门禁不变量守卫（SPEC-L0 §5.1）。

归属 l0-contracts 阻断 job（G0-4）：测试失败即 CI 变红。
C2 六能力 port 契约测试完成后并入本目录。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
L0_FOUNDATION = REPO_ROOT / "34-前端应用训练系统" / "core" / "l0_foundation.py"


def test_g0_3_no_module_level_sys_path_insert():
    """G0-3：l0_foundation.py 禁止模块级 sys.path.insert 与模块级 import dc_pg。"""
    src = L0_FOUNDATION.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        # 模块级判定：无缩进
        if not line.startswith((" ", "\t")) and stripped.startswith("sys.path.insert"):
            raise AssertionError(f"G0-3 违规：l0_foundation.py:{i} 模块级 sys.path.insert")
        if not line.startswith((" ", "\t")) and re.match(r"^import\s+dc_pg\b", stripped):
            raise AssertionError(f"G0-3 违规：l0_foundation.py:{i} 模块级 import dc_pg")


def test_g0_1_no_plaintext_pg_password():
    """G0-1：l0_foundation.py 禁止口令字面量（FIS_PG_PASSWORD 仅允许环境变量读取）。"""
    src = L0_FOUNDATION.read_text(encoding="utf-8")
    # 环境变量读取形态：os.environ.get("FIS_PG_PASSWORD") —— 允许
    # 字面量默认值形态：os.environ.get("FIS_PG_PASSWORD", "xxx") —— 禁止
    bad = re.search(r'FIS_PG_PASSWORD"?\s*,\s*["\'][^"\']{8,}["\']', src)
    assert bad is None, f"G0-1 违规：l0_foundation.py 检出 FIS_PG_PASSWORD 字面量默认值: {bad.group(0)!r}"


def test_g0_2_fis_p0_path_externalized():
    """G0-2：fis-p0 绝对路径必须经 _FIS_P0_HOME 配置，禁止硬编码。"""
    src = L0_FOUNDATION.read_text(encoding="utf-8")
    assert "/home/ubuntu/fis-p0/scripts/search_cli.py" not in src, "G0-2 违规：search_cli.py 路径硬编码"
    assert "/home/ubuntu/fis-p0/.venv/bin/python" not in src, "G0-2 违规：venv python 路径硬编码"
    assert "_FIS_P0_HOME" in src, "G0-2 违规：缺少 _FIS_P0_HOME 配置入口"
