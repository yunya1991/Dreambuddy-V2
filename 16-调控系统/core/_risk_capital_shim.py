"""旧路径兼容 shim 工具：把 16-调控系统/core 下的旧包名重定向到 13/risk_capital。

为什么不用「只转发 __init__」的写法：
    仅替换 ``sys.modules[alias]`` 时，``from capital_control.types import X`` 会再
    按别名创建一份全新的子模块对象，导致同一个类出现两个副本，
    ``isinstance`` / 异常类型判断全部失效。这里用 MetaPathFinder 把
    ``<alias>`` 与 ``<alias>.<sub>`` 直接别名到 ``<real>`` 的同一模块对象。

安装顺序很关键：必须先挂 finder，再导入真实包。否则真实包在 import 期间
对子模块的旧路径引用会先创建出「别名副本」。
"""

import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

_RISK_DIR = Path(__file__).resolve().parents[2] / "13-通用风控模块"
if str(_RISK_DIR) not in sys.path:
    sys.path.insert(0, str(_RISK_DIR))


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, module):
        self._module = module

    def create_module(self, spec):
        return self._module

    def exec_module(self, module):
        return None


class _AliasFinder(importlib.abc.MetaPathFinder):
    """把 alias_name 及其子模块解析为 real_name 对应模块的同一对象。"""

    def __init__(self, alias_name: str, real_name: str):
        self.alias_name = alias_name
        self.real_name = real_name

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.alias_name:
            real_name = self.real_name
        elif fullname.startswith(self.alias_name + "."):
            real_name = self.real_name + fullname[len(self.alias_name) :]
        else:
            return None
        try:
            module = importlib.import_module(real_name)
        except ImportError:
            return None
        sys.modules[fullname] = module
        return importlib.util.spec_from_loader(fullname, _AliasLoader(module))


def install(alias_name: str, real_name: str):
    """注册别名包与子模块别名 finder。返回真实包对象。"""
    finder = None
    for item in sys.meta_path:
        if (
            isinstance(item, _AliasFinder)
            and item.alias_name == alias_name
            and item.real_name == real_name
        ):
            finder = item
            break
    if finder is None:
        sys.meta_path.insert(0, _AliasFinder(alias_name, real_name))

    real_pkg = importlib.import_module(real_name)
    sys.modules[alias_name] = real_pkg

    # 真实包在 import 期间已加载的子模块（如 types）先登记别名，
    # 避免调用方紧接着的 `from capital_control.types import ...` 在
    # 父包替换边界上创建出重复模块对象。
    real_prefix = real_name + "."
    for mod_name, module in list(sys.modules.items()):
        if mod_name.startswith(real_prefix):
            alias_child = alias_name + mod_name[len(real_name) :]
            sys.modules.setdefault(alias_child, module)
    return real_pkg
