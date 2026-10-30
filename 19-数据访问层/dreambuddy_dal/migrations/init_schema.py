"""DDL 唯一 owner：SQLite schema 显式初始化入口（G0-6，SPEC-L0 §5.1）。

用法（部署流程显式执行，业务层禁止建表）：
    python -m dreambuddy_dal.migrations.init_schema
    python -m dreambuddy_dal.migrations.init_schema --db-path /path/to/db

幂等：init_db_schema 全部 CREATE TABLE IF NOT EXISTS。
"""
import argparse
import os


def init_schema(db_path: str) -> int:
    """对指定 SQLite 库执行幂等 schema 初始化，返回表数。"""
    from dreambuddy_dal.connection import get_sqlite_connection
    from dreambuddy_dal.implementations.sqlite_unified import init_db_schema

    with get_sqlite_connection(db_path) as conn:
        init_db_schema(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite schema 初始化（DDL 唯一 owner）")
    parser.add_argument(
        "--db-path",
        default=os.environ.get(
            "DAL_DB_PATH",
            os.path.join(os.environ.get("DATA_DIR", "./data"), "dreambuddy_core.db"),
        ),
        help="目标 SQLite 库路径（默认 DAL_DB_PATH / DATA_DIR 推导）",
    )
    args = parser.parse_args()
    count = init_schema(args.db_path)
    print(f"[init_schema] OK db={args.db_path} tables={count}")


if __name__ == "__main__":
    main()
