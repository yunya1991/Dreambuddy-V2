"""Deploy Gate — L2-8B 灰度自动部署闸门（影子验证 → 灰度 auto）

SPEC-33-G：
  - §2.7.1 影子运行：`evo/*` 部署到影子通道与在线版本同输入对跑，影子 pass 才可前进
  - §2.8 八门禁 / §2.8.1 三段式 S1-S3 / §2.8.2 断路器（连续回滚冻结 7 天）
  - §2.11.4 L2-8 部署分层：A 自动合入 → B 自动部署灰度 → C 生产自动部署（非目标）
  - §2.11.7 部署边界：合入 ≠ 上线；生产自动部署非目标；DDL/schema/契约/registry/定时任务/
    交易链路/有状态变更一律人工；未演练不得开自动部署；部署失败回滚后立即冻结 auto 7 天
  - §2.11.8 三权分立：部署权在发布系统，编排器不得持有部署凭据
  - §4 硬约束 19-26；§5 回滚表（灰度部署走 `rollback_deploy.sh --env gray`）

部署侧必备（缺一不得开启任何自动部署）：
  健康检查（url/cmd + 核心链路冒烟）、一键回滚脚本且演练通过、部署窗口（避开交易时段
  与定时任务）、单实例重启 flock + pidfile、数据迁移闸门。

工程约束：纯标准库；禁止网络（仅本地文件 + 子进程 + fcntl/flock）；状态文件原子写
（os.replace）；流水 JSONL append-only；默认 mode=off；任何未知/损坏状态一律 fail-closed。
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

ENV_GRAY = "gray"
MODE_OFF, MODE_SHADOW, MODE_AUTO = "off", "shadow", "auto"
MODES = (MODE_OFF, MODE_SHADOW, MODE_AUTO)

SHANGHAI = timezone(timedelta(hours=8))
DEFAULT_WINDOW = ("09:15", "15:05")
DEFAULT_BLOCKED_WEEKDAYS = (0, 1, 2, 3, 4)
STAGES = ("S1", "S2", "S3")
FREEZE_DAYS = 7
STATE_FLAGS = ("ddl", "schema", "registry", "cron", "stateful", "trading")
MIGRATION_MARKERS = ("migration/", "migrations/", ".sql", "schema", "registry")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG: Dict[str, Any] = {
    "env": ENV_GRAY,
    "health": {},
    "rollback_script": "",
    "drill_max_age_days": 30,
    "window": {"start": DEFAULT_WINDOW[0], "end": DEFAULT_WINDOW[1]},
    "blocked_weekdays": list(DEFAULT_BLOCKED_WEEKDAYS),
    "cron_slots": [],
    "cron_guard_minutes": 30,
    "lock_path": "",
    "pidfile_path": "",
    "min_shadow_runs": 3,
}


class DeployBlocked(ValueError):
    """灰度自动部署前置条件不满足（硬拒绝）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeployBlocked(message)


def _merge_config(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_hhmm(value: Any, default: Optional[int] = None) -> Optional[int]:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if ":" not in text:
        return default
    hour_text, _, minute_text = text.partition(":")
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return hour * 60 + minute


def _resolve_path(value: Any) -> Optional[Path]:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class SingleInstanceLock:
    """flock 独占 + pidfile：同一环境同一时刻只允许一个部署进程。

    flock 随进程退出自动释放，因此 pidfile 存在但锁空闲时可安全接管（stale pid）。
    """

    def __init__(
        self,
        lock_path: str | Path,
        pidfile_path: str | Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.lock_path = Path(lock_path)
        self.pidfile_path = Path(pidfile_path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._handle = None
        self._info: Optional[Dict[str, Any]] = None

    def acquire(self) -> Dict[str, Any]:
        if self._handle is not None:
            return dict(self._info or {})
        _require(bool(str(self.lock_path)), "lock_path 未配置，禁止部署（单实例校验缺失）")
        _require(bool(str(self.pidfile_path)), "pidfile_path 未配置，禁止部署（单实例校验缺失）")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.pidfile_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            holder = self._read_pidfile()
            raise DeployBlocked(
                f"部署锁已被占用：{self.lock_path}（pid={holder or 'unknown'}），拒绝重入"
            ) from None
        stale = self._stale_pid()
        self._handle = handle
        self._write_pidfile(os.getpid())
        self._info = {
            "lock_path": str(self.lock_path),
            "pidfile_path": str(self.pidfile_path),
            "pid": os.getpid(),
            "acquired_at": self.clock().isoformat(),
            "stale_pid": stale,
        }
        return dict(self._info)

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
            self._info = None
        if self._read_pidfile() == str(os.getpid()):
            try:
                self.pidfile_path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> Dict[str, Any]:
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    # ---------------------------------------------------------------- 内部

    def _read_pidfile(self) -> str:
        try:
            return self.pidfile_path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""

    def _write_pidfile(self, pid: int) -> None:
        self.pidfile_path.write_text(f"{pid}\n", encoding="utf-8")

    def _stale_pid(self) -> Optional[str]:
        """锁已空闲但 pidfile 残留：pid 已死（或非法）→ 视为 stale，可接管。"""
        holder = self._read_pidfile()
        if not holder:
            return None
        try:
            pid = int(holder)
        except ValueError:
            return holder
        if pid == os.getpid():
            return None
        return None if _pid_alive(pid) else holder


class DeployGate:
    """灰度自动部署的唯一入口：mode=off → shadow（影子验证）→ auto（灰度发布）。"""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.root = Path(root)
        self.deploy_dir = self.root / "deploy"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.config = _merge_config(DEFAULT_CONFIG, config or {})

    # ---------------------------------------------------------------- 路径

    @property
    def mode_path(self) -> Path:
        return self.deploy_dir / "deploy_mode.json"

    @property
    def shadow_runs_path(self) -> Path:
        return self.deploy_dir / "shadow_runs.jsonl"

    @property
    def freeze_path(self) -> Path:
        return self.deploy_dir / "freeze.json"

    @property
    def audit_path(self) -> Path:
        return self.deploy_dir / "audit.jsonl"

    @property
    def releases_dir(self) -> Path:
        return self.deploy_dir / "releases"

    def _release_path(self, env: str) -> Path:
        return self.releases_dir / f"{env}.json"

    # ---------------------------------------------------------------- 模式

    def mode(self) -> str:
        doc = self._load_json(self.mode_path)
        if not doc:
            return MODE_OFF
        value = str(doc.get("mode") or "").strip().lower()
        return value if value in MODES else MODE_OFF

    def set_mode(self, mode: str, *, actor: str = "operator") -> Dict[str, Any]:
        target = str(mode or "").strip().lower()
        _require(target in MODES, f"非法部署模式：{mode!r}（仅支持 {MODES}）")
        current = self.mode()
        if target == MODE_AUTO and current != MODE_AUTO:
            minimum = int(self.config["min_shadow_runs"])
            passes = self.consecutive_shadow_passes()
            _require(
                passes >= minimum,
                f"开启 auto 前需连续 {minimum} 次影子成功（当前 {passes}），禁止跳过影子验证",
            )
            _require(
                not self.is_frozen(),
                f"自动部署处于冻结期（{self._freeze_until_text()}），拒绝开启 auto",
            )
        document = {
            "mode": target,
            "previous_mode": current,
            "actor": actor or "operator",
            "updated_at": self.clock().isoformat(),
        }
        self._write_json(self.mode_path, document)
        self._audit(
            "mode_change", {"mode": target, "previous": current, "actor": document["actor"]}
        )
        return {"mode": target, "previous": current, "at": document["updated_at"]}

    def record_shadow_run(self, *, change_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        change_id = str(change_id or "").strip()
        _require(bool(change_id), "change_id is required")
        payload = dict(result or {})
        passed = payload.get("overall") == "pass"
        self._append_jsonl(
            self.shadow_runs_path,
            {
                "change_id": change_id,
                "overall": payload.get("overall"),
                "passed": passed,
                "at": self.clock().isoformat(),
                "result": payload,
            },
        )
        return {
            "change_id": change_id,
            "passed": passed,
            "consecutive_passes": self.consecutive_shadow_passes(),
        }

    def consecutive_shadow_passes(self) -> int:
        """影子流水尾部连续 pass 计数；遇到失败/损坏行立即停止（fail-closed）。"""
        path = self.shadow_runs_path
        if not path.is_file():
            return 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        count = 0
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                break
            if not isinstance(row, dict) or not row.get("passed"):
                break
            count += 1
        return count

    def is_frozen(self) -> bool:
        doc = self._load_json(self.freeze_path)
        if doc is None:
            return False
        until = _parse_ts(doc.get("frozen_until"))
        if until is None:
            return True
        return _utc(self.clock()) < _utc(until)

    # ---------------------------------------------------------------- 就绪

    def readiness(
        self,
        *,
        change_id: str,
        change: Dict[str, Any],
        shadow_report: Any = None,
        drill_report: Any = None,
        stage: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cfg = _merge_config(self.config, config or {})
        mode = self.mode()
        doc = dict(change or {})
        checks = [
            self._check_mode(mode),
            self._check_stage(mode, self._stage_value(stage)),
            self._check_shadow(shadow_report),
            self._check_health(cfg),
            self._check_rollback(cfg, drill_report),
            self._check_window(cfg),
            self._check_single_instance(cfg),
            self._check_data_migration(doc),
            self._check_freeze(),
            self._check_change_id(change_id),
        ]
        blockers = [
            f"{item['id']}: {item['reason']}" for item in checks if item["status"] != "pass"
        ]
        return {"mode": mode, "allowed": not blockers, "checks": checks, "blockers": blockers}

    # ---------------------------------------------------------------- 部署

    def deploy(
        self,
        *,
        change_id: str,
        change: Dict[str, Any],
        deploy_fn: Callable[[], Any],
        health_fn: Callable[[], Any],
        rollback_fn: Callable[[str], Any],
        shadow_report: Any = None,
        drill_report: Any = None,
        stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        report = self.readiness(
            change_id=change_id,
            change=change,
            shadow_report=shadow_report,
            drill_report=drill_report,
            stage=stage,
        )
        if not report["allowed"]:
            raise DeployBlocked("自动部署被拒绝：" + "；".join(report["blockers"]))

        mode = report["mode"]
        doc = dict(change or {})
        change_id = str(change_id).strip()
        env = str(self.config.get("env") or ENV_GRAY).strip() or ENV_GRAY

        if mode == MODE_SHADOW:
            shadow = self.record_shadow_run(
                change_id=change_id,
                result={"overall": "pass", "mode": MODE_SHADOW, "simulated": True},
            )
            self._audit(
                "deploy_simulated",
                {
                    "change_id": change_id,
                    "env": env,
                    "consecutive_passes": shadow["consecutive_passes"],
                },
            )
            return {
                "status": "simulated",
                "deployed": False,
                "would_deploy": True,
                "rolled_back": False,
                "change_id": change_id,
                "env": env,
                "readiness": report,
                "shadow": shadow,
            }

        lock = SingleInstanceLock(
            str(self.config.get("lock_path") or ""),
            str(self.config.get("pidfile_path") or ""),
            clock=self.clock,
        )
        lock.acquire()
        try:
            target = self._target_version(change_id, doc)
            previous = self._release_current(env)
            try:
                deploy_fn()
            except Exception as exc:  # 部署失败一律回滚 + 冻结，不吞成成功
                return self._fail_closed(
                    env=env,
                    change_id=change_id,
                    previous=previous,
                    reason=f"deploy 异常：{exc}",
                    rollback_fn=rollback_fn,
                    report=report,
                )

            health = health_fn()
            if not self._health_ok(health):
                return self._fail_closed(
                    env=env,
                    change_id=change_id,
                    previous=previous,
                    reason=f"健康检查未通过（{self._health_text(health)}）",
                    rollback_fn=rollback_fn,
                    report=report,
                )

            release_doc = self._load_json(self._release_path(env)) or {}
            release_doc["current"] = target
            release_doc["previous"] = previous
            release_doc["change_id"] = change_id
            release_doc["released_at"] = self.clock().isoformat()
            self._write_json(self._release_path(env), release_doc)
            self._audit(
                "deploy_success",
                {"change_id": change_id, "env": env, "version": target["version"]},
            )
            return {
                "status": "deployed",
                "deployed": True,
                "would_deploy": True,
                "rolled_back": False,
                "change_id": change_id,
                "env": env,
                "release": {"current": target, "previous": previous},
                "readiness": report,
            }
        finally:
            lock.release()

    # ---------------------------------------------------------------- 检查项

    def _check_mode(self, mode: str) -> Dict[str, str]:
        if mode == MODE_OFF:
            return {
                "id": "mode",
                "status": "fail",
                "reason": "部署模式 off（deploy_mode.json 缺失、损坏或未开启），禁止自动部署",
            }
        return {"id": "mode", "status": "pass", "reason": f"部署模式 {mode}"}

    def _check_stage(self, mode: str, stage: str) -> Dict[str, str]:
        if mode == MODE_AUTO:
            if stage == "S3":
                return {"id": "stage", "status": "pass", "reason": "stage=S3，允许 auto"}
            return {
                "id": "stage",
                "status": "fail",
                "reason": f"auto 仅允许 stage=S3（当前 {stage}），S1/S2 不得自动部署",
            }
        if stage in ("S2", "S3"):
            return {"id": "stage", "status": "pass", "reason": f"stage={stage}，允许影子验证"}
        return {
            "id": "stage",
            "status": "fail",
            "reason": f"shadow 需 stage ∈ {{S2,S3}}（当前 {stage}）；S1 数据积累期为 manual，不启影子",
        }

    @staticmethod
    def _check_shadow(shadow_report: Any) -> Dict[str, str]:
        overall = shadow_report.get("overall") if isinstance(shadow_report, dict) else shadow_report
        if overall == "pass":
            return {"id": "shadow", "status": "pass", "reason": "影子验证 overall=pass"}
        return {
            "id": "shadow",
            "status": "fail",
            "reason": f"影子验证未通过（overall={overall!r}）；灰度前必须先跑影子模式并 pass",
        }

    @staticmethod
    def _check_health(cfg: Dict[str, Any]) -> Dict[str, str]:
        health = cfg.get("health")
        if not isinstance(health, dict):
            return {
                "id": "health",
                "status": "fail",
                "reason": "健康检查契约缺失（config.health 必须是对象）",
            }
        endpoint = str(health.get("url") or "").strip()
        command = str(health.get("cmd") or "").strip()
        smoke = [str(item).strip() for item in (health.get("smoke") or []) if str(item).strip()]
        if not endpoint and not command:
            return {
                "id": "health",
                "status": "fail",
                "reason": "健康检查未声明（需 url 或 cmd），禁止自动部署",
            }
        if not smoke:
            return {
                "id": "health",
                "status": "fail",
                "reason": "健康检查未覆盖核心链路（smoke 为空），禁止自动部署",
            }
        return {
            "id": "health",
            "status": "pass",
            "reason": f"健康检查已声明（{'url' if endpoint else 'cmd'} + {len(smoke)} 项冒烟）",
        }

    def _check_rollback(self, cfg: Dict[str, Any], drill_report: Any) -> Dict[str, str]:
        script = _resolve_path(cfg.get("rollback_script"))
        if script is None or not script.is_file():
            return {
                "id": "rollback",
                "status": "fail",
                "reason": f"一键回滚脚本不存在：{cfg.get('rollback_script') or '<未配置>'}",
            }
        if not isinstance(drill_report, dict) or drill_report.get("overall") != "pass":
            return {
                "id": "rollback",
                "status": "fail",
                "reason": "回滚演练未通过（drill_report.overall != pass），未演练不得开启自动部署",
            }
        checked_at = _parse_ts(
            drill_report.get("checked_at") or drill_report.get("at") or drill_report.get("drill_at")
        )
        if checked_at is None:
            return {
                "id": "rollback",
                "status": "fail",
                "reason": "回滚演练报告缺 checked_at，无法判断时效",
            }
        max_days = int(cfg.get("drill_max_age_days") or 30)
        age = _utc(self.clock()) - _utc(checked_at)
        if age < timedelta(0):
            return {
                "id": "rollback",
                "status": "fail",
                "reason": f"回滚演练时间在未来（{checked_at.isoformat()}），拒绝采信",
            }
        if age > timedelta(days=max_days):
            return {
                "id": "rollback",
                "status": "fail",
                "reason": f"回滚演练报告过期（{age.days} 天 > {max_days} 天上限），须重新演练",
            }
        return {
            "id": "rollback",
            "status": "pass",
            "reason": f"回滚脚本存在且演练 pass（{age.days} 天前）",
        }

    def _check_window(self, cfg: Dict[str, Any]) -> Dict[str, str]:
        now = self._local_now()
        window = cfg.get("window") if isinstance(cfg.get("window"), dict) else {}
        start = _parse_hhmm(window.get("start"), _parse_hhmm(DEFAULT_WINDOW[0]))
        end = _parse_hhmm(window.get("end"), _parse_hhmm(DEFAULT_WINDOW[1]))
        weekdays_value = cfg.get("blocked_weekdays")
        if weekdays_value is None:
            weekdays = set(DEFAULT_BLOCKED_WEEKDAYS)
        else:
            try:
                weekdays = {int(item) for item in weekdays_value}
            except (TypeError, ValueError):
                return {
                    "id": "deploy_window",
                    "status": "fail",
                    "reason": "blocked_weekdays 配置非法，无法确认部署窗口（fail-closed）",
                }
        minutes = now.hour * 60 + now.minute
        if start is not None and end is not None and now.weekday() in weekdays:
            if start <= minutes < end:
                return {
                    "id": "deploy_window",
                    "status": "fail",
                    "reason": (
                        f"当前 {now.strftime('%Y-%m-%d %H:%M')} 处于禁止部署窗口 "
                        f"{window.get('start') or DEFAULT_WINDOW[0]}-{window.get('end') or DEFAULT_WINDOW[1]}"
                        "（交易时段），禁止自动部署"
                    ),
                }
        guard = int(cfg.get("cron_guard_minutes") or 30)
        for slot in cfg.get("cron_slots") or []:
            slot_minutes = _parse_hhmm(slot, None)
            if slot_minutes is None:
                continue
            if abs(minutes - slot_minutes) <= guard:
                return {
                    "id": "deploy_window",
                    "status": "fail",
                    "reason": f"当前时间与定时任务 {slot} 冲突（±{guard} 分钟），禁止自动部署",
                }
        return {
            "id": "deploy_window",
            "status": "pass",
            "reason": f"当前 {now.strftime('%Y-%m-%d %H:%M')} 不在禁止窗口/定时任务冲突区",
        }

    @staticmethod
    def _check_single_instance(cfg: Dict[str, Any]) -> Dict[str, str]:
        lock_path = str(cfg.get("lock_path") or "").strip()
        pidfile_path = str(cfg.get("pidfile_path") or "").strip()
        if not lock_path or not pidfile_path:
            return {
                "id": "single_instance",
                "status": "fail",
                "reason": "单实例校验缺失（需同时配置 lock_path 与 pidfile_path）",
            }
        return {
            "id": "single_instance",
            "status": "pass",
            "reason": f"flock+pidfile 已配置（{lock_path}）",
        }

    @staticmethod
    def _check_data_migration(change: Dict[str, Any]) -> Dict[str, str]:
        flags = change.get("flags") if isinstance(change.get("flags"), dict) else {}
        flag_hits = [name for name in STATE_FLAGS if bool(flags.get(name))]
        files = [str(item).strip() for item in (change.get("files") or []) if str(item).strip()]
        file_hits = [
            path
            for path in files
            if any(marker in path.lower().replace("\\", "/") for marker in MIGRATION_MARKERS)
        ]
        if not flag_hits and not file_hits:
            return {
                "id": "data_migration",
                "status": "pass",
                "reason": "无 DDL/schema/registry/定时任务/有状态/交易链路变更",
            }
        detail = "、".join(flag_hits + file_hits)
        return {
            "id": "data_migration",
            "status": "fail",
            "reason": f"变更涉及 {detail}：必须人工部署 + 状态恢复演练，禁止自动（L2-9）",
        }

    def _check_freeze(self) -> Dict[str, str]:
        if not self.is_frozen():
            return {"id": "freeze", "status": "pass", "reason": "无生效中的部署冻结"}
        return {
            "id": "freeze",
            "status": "fail",
            "reason": f"自动部署冻结中（frozen_until={self._freeze_until_text()}），拒绝部署",
        }

    @staticmethod
    def _check_change_id(change_id: Any) -> Dict[str, str]:
        if str(change_id or "").strip():
            return {"id": "change_id", "status": "pass", "reason": "change_id 已提供"}
        return {"id": "change_id", "status": "fail", "reason": "change_id 为空，无法归因"}

    # ---------------------------------------------------------------- 内部

    def _stage_value(self, stage: Optional[str]) -> str:
        if stage is not None:
            value = str(stage).strip().upper()
        else:
            doc = self._load_json(self.root / "stage.json") or {}
            value = str(doc.get("stage") or "").strip().upper()
        return value if value in STAGES else "S1"

    def _fail_closed(
        self,
        *,
        env: str,
        change_id: str,
        previous: Optional[Dict[str, Any]],
        reason: str,
        rollback_fn: Callable[[str], Any],
        report: Dict[str, Any],
    ) -> Dict[str, Any]:
        rollback_error = ""
        try:
            rollback_fn(reason)
        except Exception as exc:  # 回滚自身失败也必须冻结，交由人工接管
            rollback_error = str(exc)
        frozen_until = self.clock() + timedelta(days=FREEZE_DAYS)
        self._write_json(
            self.freeze_path,
            {
                "change_id": change_id,
                "env": env,
                "reason": reason,
                "frozen_at": self.clock().isoformat(),
                "frozen_until": frozen_until.isoformat(),
            },
        )
        self._audit(
            "deploy_rolled_back",
            {
                "change_id": change_id,
                "env": env,
                "reason": reason,
                "frozen_until": frozen_until.isoformat(),
                "rollback_error": rollback_error,
            },
        )
        return {
            "status": "rolled_back",
            "deployed": False,
            "would_deploy": True,
            "rolled_back": True,
            "change_id": change_id,
            "env": env,
            "reason": reason,
            "frozen_until": frozen_until.isoformat(),
            "rollback_error": rollback_error,
            "release": {"current": previous},
            "readiness": report,
        }

    def _target_version(self, change_id: str, change: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "version": str(change.get("version") or change_id).strip(),
            "commit": str(change.get("commit") or "").strip(),
            "released_at": self.clock().isoformat(),
        }

    def _release_current(self, env: str) -> Optional[Dict[str, Any]]:
        doc = self._load_json(self._release_path(env))
        current = (doc or {}).get("current")
        return dict(current) if isinstance(current, dict) else None

    def _local_now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=SHANGHAI)
        return now.astimezone(SHANGHAI)

    def _freeze_until_text(self) -> str:
        doc = self._load_json(self.freeze_path) or {}
        return str(doc.get("frozen_until") or "<损坏的 freeze.json>")

    @staticmethod
    def _health_ok(value: Any) -> bool:
        if value is True:
            return True
        if isinstance(value, dict):
            return value.get("status") == "pass" or value.get("overall") == "pass"
        return False

    @staticmethod
    def _health_text(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("status") or value.get("overall") or "fail")
        return repr(value)

    @staticmethod
    def _load_json(path: Path) -> Optional[Dict[str, Any]]:
        """文件不存在 → None；损坏/非对象 → {}（调用方按 fail-closed 处理）。"""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return {}
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return doc if isinstance(doc, dict) else {}

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)

    @staticmethod
    def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def _audit(self, event: str, payload: Dict[str, Any]) -> None:
        row = {"event": event, "at": self.clock().isoformat()}
        row.update(payload)
        self._append_jsonl(self.audit_path, row)


__all__ = [
    "ENV_GRAY",
    "MODE_AUTO",
    "MODE_OFF",
    "MODE_SHADOW",
    "DeployBlocked",
    "DeployGate",
    "SingleInstanceLock",
]
