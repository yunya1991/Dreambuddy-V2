from pathlib import Path


def test_workspace_paths_resolve():
    from scripts.memory_l4.paths import workspace_root, memory_l4_dir

    root = workspace_root()
    assert isinstance(root, Path)
    assert (root / ".workbuddy").exists()

    l4 = memory_l4_dir()
    assert l4.name == "memory_l4"

