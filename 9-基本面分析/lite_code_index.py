from pathlib import Path
import runpy


_CURRENT_FILE = Path(__file__).resolve()
_SOURCE_FILE = _CURRENT_FILE.parent / "backend" / "src" / "lite_code_index.py"

if not _SOURCE_FILE.exists():
    raise FileNotFoundError(str(_SOURCE_FILE))

globals().update(runpy.run_path(str(_SOURCE_FILE), run_name=__name__))
