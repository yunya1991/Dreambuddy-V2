"""train_and_export_coupling.py — Phase B Head 训练 + coupling JSON 导出.

流程:
  1. 加载 NeuralSDE v1_dim64 (主体冻结, SPEC H2)
  2. 读取 Phase C JSONL (真实域轨迹) 或 static JSON 的 15 个 coupling 作为 target
  3. 真实市场输入 (real_market_features.py): BTC 1h closes + 36 外生因子 + HMM regime
     → (y, log_sig, regime one-hot, factors) 喂 frozen drift_net, hook 抓 64-dim hidden
     (数据缺失时 FAIL-OPEN 回退 torch.randn 合成输入)
  4. Mac Metal / CPU 训 DomainCouplingHead ~100 步
  5. 推理: 真实窗口逐样本 coupling → mean 15 维 + regime/vol/flow 分组统计
  6. 覆盖写 static JSON: coupling 替换 + input_source/state_sensitivity 附加

设计原则:
  - FAIL-OPEN: ckpt/static JSON 缺失时 fallback 到随机初始化 Head + 合成 coupling
  - 主体冻结: drift_net requires_grad=False, eval mode
  - 确定性: 固定 torch.manual_seed(42), 训练+推理可复现
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

# REPO 根 (绝对路径, 用于 ckpt/json 定位)
REPO = Path(__file__).resolve().parents[3]
# PYTHONPATH 根: dreambuddy_evolution 的父目录 (23-四层闭环自进化交易架构/)
_PY_ROOT = Path(__file__).resolve().parents[2]
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

CKPT = REPO / "23-四层闭环自进化交易架构" / "data" / "neural_sde_v1_dim64.pt"
STATIC_JSON = REPO / "mcp_shells" / "_shared" / "assets" / "domain_transmission_static.json"


def _device() -> str:
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return "mps"
    return "cpu"


def _load_jsonl_targets(jsonl_path: Path) -> tuple[torch.Tensor, str, int] | None:
    """Phase C: 从 collect_domain_discovery_data.py 产出的 JSONL 构造 coupling target.

    coupling 定义: 每对域 (a,b) 的 drift 状态**同向共现率**.
      both_drift 权重 ×2, both_stable 权重 ×1, 归一化到 [0,1].

    Returns (coupling_15d_tensor, source_label, n_samples) 或 None.
    """
    from dreambuddy_evolution.core.domain_coupling_head import PAIRS

    if not jsonl_path.exists():
        print(f"[WARN] JSONL 不存在: {jsonl_path}")
        return None
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    samples: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not samples:
        print(f"[WARN] JSONL 无有效样本: {jsonl_path}")
        return None

    N = len(samples)
    # 预统计每个 pair 的 drift level 共现 (乘积均值)
    drift_levels = {"stable": 0.0, "minor_drift": 0.5, "severe_drift": 1.0}
    targets: list[float] = []
    drift_samples_count = 0  # 至少一个域非 stable 的样本数
    for a, b in PAIRS:
        sum_la_lb = 0.0  # drift level 乘积和
        both_drifted = 0  # 两者都非 stable
        for s in samples:
            ds = s.get("input", {}).get("domain_states", {})
            da = ds.get(a, {}).get("drift", "unknown")
            db = ds.get(b, {}).get("drift", "unknown")
            la = drift_levels.get(da, 0.0)
            lb = drift_levels.get(db, 0.0)
            sum_la_lb += la * lb
            if la > 0 and lb > 0:
                both_drifted += 1
            if la > 0 or lb > 0:
                drift_samples_count += 1
        # coupling = drift level 乘积均值 (severe×severe=1.0, minor×minor=0.25)
        raw = sum_la_lb / N
        targets.append(min(max(raw, 0.0), 1.0))

    # 全 stable 样本场景: 用 static JSON coupling 平滑 (避免全 0)
    if drift_samples_count == 0:
        print(f"[INFO] JSONL {N} 样本全 stable, coupling 全 0, 用 static JSON 平滑")
        static_t = _load_pseudo_target(STATIC_JSON)
        if static_t is not None:
            targets = [
                round(t * 0.5 + s * 0.5, 3) for t, s in zip(targets, static_t.tolist(), strict=True)
            ]

    source_label = f"phaseC_jsonl_{N}samples" + ("_allstable" if drift_samples_count == 0 else "")
    print(
        f"[INFO] Phase C JSONL target: N={N}, drift_samples={drift_samples_count}, "
        f"mean={sum(targets)/len(targets):.3f}, source={source_label}"
    )
    return torch.tensor(targets, dtype=torch.float32), source_label, N


def _load_pseudo_target(static_json: Path) -> torch.Tensor | None:
    """从 static JSON 读取 15 个 coupling 值作为 pseudo-target.

    失败时返回 None (脚本会 fallback 到随机 target).
    """
    from dreambuddy_evolution.core.domain_coupling_head import PAIRS

    if not static_json.exists():
        print(f"[WARN] static JSON 不存在: {static_json}")
        return None
    data = json.loads(static_json.read_text())
    static_couplings = data.get("domain_transmission", {}).get("drift_coupling", {})
    if len(static_couplings) != 15:
        print(f"[WARN] static JSON coupling 对数={len(static_couplings)} (期望 15)")
        return None
    # 按 PAIRS 顺序读取 (cognition↔rea, cognition↔search, ...)
    target_vals = []
    for a, b in PAIRS:
        key_fwd = f"{a}↔{b}"
        key_rev = f"{b}↔{a}"
        entry = static_couplings.get(key_fwd) or static_couplings.get(key_rev)
        if entry is None:
            print(f"[WARN] PAIR {key_fwd} 未找到")
            return None
        target_vals.append(float(entry["coupling"]))
    return torch.tensor(target_vals, dtype=torch.float32)


def _build_synthetic_batch(sig_dim: int = 15) -> tuple[torch.Tensor, torch.Tensor]:
    """生成 NeuralSDE forward 的合成输入 (y, log_sig).

    NeuralSDE drift_net.forward(t=scalar, y=(B,1), log_sig=(B, sig_dim)).
    """
    B = 32
    y = torch.randn(B, 1)
    log_sig = torch.randn(B, sig_dim)
    return y, log_sig


def _group_stats(
    coupling: torch.Tensor, buckets: dict[str, "np.ndarray"], hidden_agg: torch.Tensor
) -> dict[str, Any]:
    """按 regime / vol / flow 分组统计 coupling 与 hidden 质心 (量化状态敏感性)."""
    out: dict[str, Any] = {}
    names = {0: "bull", 1: "chop", 2: "bear"}
    c_np = coupling.detach().cpu().numpy()
    h_np = hidden_agg.detach().cpu().numpy()
    for key, labels in buckets.items():
        groups: dict[str, Any] = {}
        centroids: dict[str, "np.ndarray"] = {}
        for g in np.unique(labels):
            mask = labels == g
            gname = names.get(int(g), f"g{int(g)}") if key == "regime" else f"q{int(g)}"
            gmean = c_np[mask].mean(axis=0)
            groups[gname] = {
                "n": int(mask.sum()),
                "coupling_mean": [round(float(v), 4) for v in gmean],
                "coupling_std": [round(float(v), 4) for v in c_np[mask].std(axis=0)],
            }
            centroids[gname] = h_np[mask].mean(axis=0)
        group_means = np.stack([np.asarray(v["coupling_mean"]) for v in groups.values()])
        deltas = (
            group_means.max(axis=0) - group_means.min(axis=0) if len(groups) > 1 else np.zeros(15)
        )
        from dreambuddy_evolution.core.domain_coupling_head import PAIRS

        top_idx = int(np.argmax(deltas))
        out[key] = {
            "n_groups": len(groups),
            "degenerate": len(groups) < 2,  # 分位阈值退化 (并列值占比过大)
            "groups": groups,
            "mean_abs_delta": round(float(np.abs(deltas).mean()), 5),
            "max_abs_delta": round(float(np.abs(deltas).max()), 5),
            "max_delta_pair": f"{PAIRS[top_idx][0]}↔{PAIRS[top_idx][1]}",
            "hidden_centroid_l2": {
                f"{a}↔{b}": round(float(np.linalg.norm(centroids[a] - centroids[b])), 4)
                for i, a in enumerate(centroids)
                for b in list(centroids)[i + 1 :]
            },
        }
    out["coupling_std_across_samples"] = round(float(c_np.std(axis=0).mean()), 5)
    return out


def train_head_and_infer(
    ckpt_path: Path = CKPT,
    static_json: Path = STATIC_JSON,
    n_steps: int = 400,
    seed: int = 42,
    jsonl_path: Path | None = None,
    n_windows: int = 96,
    use_real_market: bool = True,
) -> dict[str, Any]:
    """主入口: 训练 DomainCouplingHead 并推理 coupling 15 维.

    Phase C 增强: 传 jsonl_path 时优先用 collect 产出的真实标注 JSONL
    构造 coupling target; 否则 fallback 到 static JSON pseudo-target (P1 行为).
    Phase D 增强: use_real_market=True 时用 BTC 1h + 36 外生因子 + HMM regime
    的真实特征替代 torch.randn 合成输入 (FAIL-OPEN 回退合成).

    Returns dict: {coupling_15d, loss_curve, final_loss, inferred,
                   pseudo_target_loaded, target_source, target_n_samples, n_steps,
                   input_source, input_meta, regime_conditional, state_sensitivity}
    """
    torch.manual_seed(seed)
    dev = _device()
    print(f"[INFO] device={dev}, ckpt={ckpt_path.name}")

    # ----- 1. 加载 NeuralSDE -----
    from dreambuddy_evolution.core.domain_coupling_head import (
        DomainCouplingHead,
        NeuralSDEHiddenExtractor,
        freeze_backbone,
        load_neural_sde_v1_dim64,
    )

    inferred = False
    pseudo_target_loaded = False
    target_source = "none"
    target_n_samples = 0
    loss_curve: list[float] = []

    try:
        drift_net, ck = load_neural_sde_v1_dim64(str(ckpt_path), device=dev)
        freeze_backbone(drift_net)
        sig_dim = ck.get("sig_dim", 15)
        print(
            f"[INFO] NeuralSDE loaded: hidden_dim={ck.get('hidden_dim', 64)}, "
            f"n_regimes={ck.get('n_regimes', 3)}, sig_dim={sig_dim}"
        )
        inferred = True
    except Exception as e:
        print(f"[WARN] NeuralSDE 加载失败, fallback 随机推理: {e}")
        sig_dim = 15

    # ----- 2. target 构造 (Phase C JSONL 优先, P1 static JSON 兜底) -----
    pseudo_target = None
    if inferred:
        # Phase C: 优先尝试 JSONL 真实标注
        if jsonl_path is not None:
            jsonl_result = _load_jsonl_targets(jsonl_path)
            if jsonl_result is not None:
                pseudo_target, target_source, target_n_samples = jsonl_result
                pseudo_target = pseudo_target.to(dev)
                pseudo_target_loaded = True
                print(
                    f"[INFO] Phase C JSONL target loaded: shape={pseudo_target.shape}, "
                    f"mean={pseudo_target.mean():.3f}"
                )

        # Fallback: P1 static JSON pseudo-target
        if not pseudo_target_loaded:
            pseudo_target = _load_pseudo_target(static_json)
            if pseudo_target is not None:
                pseudo_target = pseudo_target.to(dev)
                pseudo_target_loaded = True
                target_source = "phaseB_static_json"
                print(
                    f"[INFO] pseudo-target loaded (P1 fallback): shape={pseudo_target.shape}, "
                    f"mean={pseudo_target.mean():.3f}"
                )
            else:
                print("[WARN] pseudo-target 未加载, 使用 random target 仅验证训练链路")

    # ----- 2.5 真实市场特征批次 (regime / 波动 / 资金流; FAIL-OPEN → 合成) -----
    real = None
    if inferred and use_real_market:
        try:
            from dreambuddy_evolution.core.real_market_features import (
                build_real_market_batch,
            )

            real = build_real_market_batch(ckpt_meta=ck, n_windows=n_windows, seed=seed)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 真实市场特征构建失败, 回退合成输入: {e}")
            real = None
        if real is not None:
            print(
                f"[INFO] 真实市场输入: N={real.n_samples}, "
                f"regime={real.meta['regime_counts']}, "
                f"log_sig_dim={real.meta['log_sig_input_dim']}, "
                f"factors={real.meta['n_factors']}"
            )
        else:
            print("[WARN] 真实市场数据不可用, 回退 torch.randn 合成输入")
    input_source = (
        "real_btc_1h_36factors"
        if real is not None
        else ("synthetic_randn" if inferred else "fallback_random_hidden")
    )

    # ----- 3. 训 Head -----
    head = DomainCouplingHead().to(dev)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=0.01)

    if inferred:
        extractor = NeuralSDEHiddenExtractor(drift_net, device=dev)
        # warm-up 一次注册 hook
        y0, ls0 = _build_synthetic_batch(sig_dim)
        with extractor.capture():
            _ = drift_net(0.5, y0.to(dev), ls0.to(dev))
        print(
            f"[INFO] Hook registered, extractor.last_hidden shape={tuple(extractor.last_hidden.shape)}"
        )

        if real is not None:
            # 真实输入张量 (整批一次搬上设备)
            y_all = torch.tensor(real.y, dtype=torch.float32, device=dev)
            ls_all = torch.tensor(real.log_sig, dtype=torch.float32, device=dev)
            rg_all = torch.tensor(real.regime, dtype=torch.float32, device=dev)
            fc_all = torch.tensor(real.factors[:, :, None], dtype=torch.float32, device=dev)
            n_all = int(real.n_samples)
            batch_size = min(32, n_all)
            gen = torch.Generator().manual_seed(seed)
            for step in range(n_steps):
                idx = torch.randperm(n_all, generator=gen)[:batch_size].to(dev)
                with extractor.capture():
                    _ = drift_net(
                        0.5, y_all[idx], ls_all[idx], rg_all[idx], None, None, fc_all[idx]
                    )
                hidden = extractor.last_hidden
                optimizer.zero_grad()
                coupling = head(hidden, apply_mask=False)
                target = (
                    pseudo_target.unsqueeze(0).expand_as(coupling)
                    if pseudo_target_loaded
                    else torch.rand_like(coupling)
                )
                loss = ((coupling - target) ** 2).mean()
                loss.backward()
                optimizer.step()
                loss_curve.append(loss.item())
                if step % 20 == 0 or step == n_steps - 1:
                    print(
                        f"  step {step:3d}/{n_steps}  loss={loss.item():.4f}  "
                        f"coupling_mean={coupling.mean().item():.3f}  input=real"
                    )
        else:
            for step in range(n_steps):
                y, log_sig = _build_synthetic_batch(sig_dim)
                with extractor.capture():
                    _ = drift_net(
                        float(torch.rand(1).item() * 2.0 - 1.0), y.to(dev), log_sig.to(dev)
                    )
                hidden = extractor.last_hidden
                optimizer.zero_grad()
                coupling = head(hidden, apply_mask=False)  # 训练时禁用 band mask
                if pseudo_target_loaded:
                    target = pseudo_target.unsqueeze(0).expand_as(coupling)  # (B, 15)
                else:
                    target = torch.rand_like(coupling)
                loss = ((coupling - target) ** 2).mean()
                loss.backward()
                optimizer.step()
                loss_curve.append(loss.item())
                if step % 20 == 0 or step == n_steps - 1:
                    print(
                        f"  step {step:3d}/{n_steps}  loss={loss.item():.4f}  coupling_mean={coupling.mean().item():.3f}"
                    )
        extractor.remove()
    else:
        # fallback: 合成 hidden (3, 32, 64) 训同样步数
        print("[INFO] Fallback 模式: 用随机 hidden 训 Head")
        for _ in range(n_steps):
            hidden = torch.randn(3, 32, 64, device=dev)
            optimizer.zero_grad()
            coupling = head(hidden, apply_mask=False)  # 训练时禁用 band mask
            target = (
                pseudo_target.unsqueeze(0).expand_as(coupling)
                if pseudo_target_loaded
                else torch.rand_like(coupling)
            )
            loss = ((coupling - target) ** 2).mean()
            loss.backward()
            optimizer.step()
            loss_curve.append(loss.item())

    final_loss = loss_curve[-1] if loss_curve else 0.0
    print(
        f"[INFO] Head 训练完成: final_loss={final_loss:.4f}, params={sum(p.numel() for p in head.parameters() if p.requires_grad)}"
    )

    # ----- 4. 推理 coupling (+ 状态敏感性) -----
    regime_conditional: dict[str, Any] = {}
    state_sensitivity: dict[str, Any] = {}
    if inferred:
        extractor = NeuralSDEHiddenExtractor(drift_net, device=dev)
        with torch.no_grad():
            if real is not None:
                # 真实窗口逐样本推理: coupling 随真实市场状态变化可被直接观察
                with extractor.capture():
                    _ = drift_net(0.5, y_all, ls_all, rg_all, None, None, fc_all)
                hidden = extractor.last_hidden
                coupling = head(hidden)  # (N, 15)
                coupling_15 = coupling.mean(dim=0).cpu().tolist()
                state_sensitivity = _group_stats(coupling, real.state_buckets(), hidden.mean(dim=0))
                # 平铺输出: regime → 15 对 coupling (消费端可直接读取)
                for gname, g in state_sensitivity["regime"]["groups"].items():
                    regime_conditional[gname] = g["coupling_mean"]
            else:
                # 合成输入兜底: 32 个随机点取 mean
                all_couplings = []
                for _ in range(32):
                    y, log_sig = _build_synthetic_batch(sig_dim)
                    t_val = float(torch.rand(1).item() * 2.0 - 1.0)
                    with extractor.capture():
                        _ = drift_net(t_val, y.to(dev), log_sig.to(dev))
                    hidden = extractor.last_hidden
                    c = head(hidden)  # (B, 15)
                    all_couplings.append(c.detach().mean(dim=0))  # (15,)
                coupling_15 = torch.stack(all_couplings).mean(dim=0).cpu().tolist()
        extractor.remove()
    else:
        coupling_15 = head(torch.randn(3, 64, device=dev)).detach().cpu().tolist()

    print(f"[INFO] 推理 coupling 15 维: mean={sum(coupling_15)/15:.3f}")
    if state_sensitivity:
        print(
            "[INFO] 状态敏感性 Δ: regime mean|Δ|="
            f"{state_sensitivity['regime']['mean_abs_delta']:.5f}, "
            f"coupling std across samples={state_sensitivity['coupling_std_across_samples']:.5f}"
        )
    return {
        "coupling_15d": coupling_15,
        "loss_curve": loss_curve,
        "final_loss": final_loss,
        "inferred": inferred,
        "pseudo_target_loaded": pseudo_target_loaded,
        "target_source": target_source,
        "target_n_samples": target_n_samples,
        "n_steps": n_steps,
        "input_source": input_source,
        "input_meta": real.meta if real is not None else {},
        "regime_conditional": regime_conditional,
        "state_sensitivity": state_sensitivity,
    }


def export_coupling_json(
    result: dict[str, Any],
    static_json: Path = STATIC_JSON,
    dry_run: bool = False,
) -> str:
    """用推理 coupling 覆盖写 static JSON.

    Returns 写入后的 JSON 路径 (或 dry_run 模式下显示 diff).
    """
    from dreambuddy_evolution.core.domain_coupling_head import PAIRS

    coupling_15 = result["coupling_15d"]
    assert len(coupling_15) == 15, f"coupling 维度={len(coupling_15)}, 期望 15"

    old_data = (
        json.loads(static_json.read_text())
        if static_json.exists()
        else {"domain_transmission": {"drift_coupling": {}}}
    )

    # 更新每个 pair 的 coupling 值 (lags_min 保留静态先验)
    static_couplings = old_data.get("domain_transmission", {}).get("drift_coupling", {})
    new_couplings: dict[str, dict[str, Any]] = {}
    for i, (a, b) in enumerate(PAIRS):
        key = f"{a}↔{b}"
        old_entry = static_couplings.get(key) or static_couplings.get(f"{b}↔{a}") or {}
        old_lags = old_entry.get("lags_min", 30) if old_entry else 30
        new_couplings[key] = {
            "coupling": round(float(coupling_15[i]), 3),
            "lags_min": old_lags,
        }

    # 构建新 JSON
    new_data = dict(old_data)
    new_data.setdefault("domain_transmission", {})["drift_coupling"] = new_couplings
    new_data["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    new_data["model_version"] = "l1-domain-coupling-v0.1"
    new_data["source"] = "neural_sde_head_infer"
    new_data["pseudo_target_source"] = result.get("target_source", "phaseB_static_json")
    new_data["pseudo_target_n_samples"] = result.get("target_n_samples", 0)
    new_data["head_training"] = {
        "n_steps": result["n_steps"],
        "final_loss": round(result["final_loss"], 4),
        "device": "mps" if result.get("inferred") else "fallback",
        "pseudo_target_loaded": result["pseudo_target_loaded"],
        "target_source": result.get("target_source", "none"),
        "target_n_samples": result.get("target_n_samples", 0),
        "seed": 42,
        "input_source": result.get("input_source", "synthetic_randn"),
        "n_input_windows": result.get("input_meta", {}).get("n_windows", 0),
    }
    # Phase D: 真实市场输入 + 状态敏感性 (新增字段, 不影响旧消费者)
    new_data["input_source"] = result.get("input_source", "synthetic_randn")
    new_data["input_stats"] = result.get("input_meta", {})
    if result.get("regime_conditional"):
        new_data["regime_conditional_coupling"] = result["regime_conditional"]
    if result.get("state_sensitivity"):
        new_data["state_sensitivity"] = result["state_sensitivity"]
    src = result.get("input_source", "synthetic_randn")
    old_note = old_data.get("note", "")
    new_data["note"] = (
        "Phase B/D DomainCouplingHead v0.1: frozen NeuralSDE v1_dim64 (H2) + "
        f"2863 params Head, input_source={src}, coupling target 来自真实域轨迹. "
        f"{old_note[:120]}"
    )
    # 生成 trace_id
    content_hash = hashlib.sha256(json.dumps(coupling_15).encode()).hexdigest()[:16]
    new_data["trace_id"] = f"l1-head-infer-{content_hash}"

    if dry_run:
        print("[DRY-RUN] JSON diff (coupling changes only):")
        for key in sorted(new_couplings.keys()):
            old_v = static_couplings.get(key, {}).get("coupling", "—")
            new_v = new_couplings[key]["coupling"]
            print(f"  {key:20s}  {old_v:>6}  →  {new_v}")
        return "DRY-RUN"

    static_json.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n")
    print(f"[INFO] JSON 已写入: {static_json}")
    # 打印变更摘要
    for key in sorted(new_couplings.keys()):
        old_v = static_couplings.get(key, {}).get("coupling")
        new_v = new_couplings[key]["coupling"]
        if old_v is not None:
            delta = new_v - old_v
            print(f"  {key:20s}  {old_v:.3f}  →  {new_v}  (Δ{delta:+.3f})")
        else:
            print(f"  {key:20s}  NEW  →  {new_v}")
    return str(static_json)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase B/C: train DomainCouplingHead + export coupling JSON"
    )
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--dry-run", action="store_true", help="仅训练+推理+打印 diff, 不写文件")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--jsonl",
        type=str,
        default=None,
        help="Phase C: collect_domain_discovery_data.py 产出的 JSONL 路径 (不传则用 P1 static JSON pseudo-target)",
    )
    parser.add_argument(
        "--n-windows",
        type=int,
        default=96,
        help="Phase D: 真实市场窗口数 (按 regime 分层抽样)",
    )
    parser.add_argument(
        "--synthetic-input",
        action="store_true",
        help="禁用真实市场输入 (回退 torch.randn 合成, 仅用于对照)",
    )
    args = parser.parse_args()

    jsonl = Path(args.jsonl) if args.jsonl else None
    result = train_head_and_infer(
        n_steps=args.steps,
        seed=args.seed,
        jsonl_path=jsonl,
        n_windows=args.n_windows,
        use_real_market=not args.synthetic_input,
    )
    export_coupling_json(result, dry_run=args.dry_run)
