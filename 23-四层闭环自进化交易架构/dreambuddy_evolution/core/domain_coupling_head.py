"""domain_coupling_head.py — L1 DomainCouplingHead MVP (Phase B).

SPEC-L0-L1-DOMAIN-DISCOVERY §4.5.1: 冻结 NeuralSDE 主体，在 3 专家的
64-dim hidden_state 上挂一个轻量 output head 输出 6×6 域间传播矩阵
（15 维上三角，忽略对角线）。

架构: 32+16+1 三层 MLP, 约 2800 可训练参数.
  (3, B, 64) experts hidden → mean pool → (B, 64)
  → Linear(64,32) → ReLU → Linear(32,16) → ReLU → Linear(16,15) → raw_couplings
  → _apply_band_mask → coupling ∈ [0,1], shape (15,)

设计原则（与 TB1 PSI drift_detector / TB3 AlphaPareto 同源）：
  - 输出带 sigmoid clip 到 [0,1]，配合 _apply_band_mask 保证物理意义
  - 主体冻结 → 仅训练 Head，占比 ≤ 0.001% 总参数量 (338KB vs <1KB)
  - 设备无关: 任何 device (cpu/mps/cuda) 都可 forward，Head 自动跟随

硬约束 H2 (SPEC §1.3): 主体冻结策略不允许微调 drift_net / diffusion_net 权重.
"""

from __future__ import annotations

import itertools
from typing import Optional

import torch
import torch.nn as nn

DOMAINS = ["cognition", "rea", "search", "semantic", "data", "eval"]
PAIRS = list(itertools.combinations(DOMAINS, 2))  # 15 对, 与 static JSON 顺序对齐
N_PAIRS = len(PAIRS)  # 15
STRONG_THRESHOLD = 0.5
WEAK_THRESHOLD = 0.3


class DomainCouplingHead(nn.Module):
    """NeuralSDE hidden_state → 6×6 domain coupling upper triangular (15-dim).

    Args:
        hidden_dim: NeuralSDE 每个专家的 hidden 维度 (默认 64).
        n_experts: MoE 专家数 (默认 3, 与 v1_dim64 checkpoint 一致).
    """

    def __init__(self, hidden_dim: int = 64, n_experts: int = 3):
        super().__init__()
        self.hidden_dim = int(hidden_dim)
        self.n_experts = int(n_experts)
        # 2803 可训练参数: (64*32+32=2080) + (32*16+16=528) + (16*15+15=255) = 2863
        self.net = nn.Sequential(
            nn.Linear(self.hidden_dim, 32),
            nn.ReLU(inplace=True),
            nn.Linear(32, 16),
            nn.ReLU(inplace=True),
            nn.Linear(16, N_PAIRS),
        )

    def forward(self, hidden: torch.Tensor, apply_mask: bool = False) -> torch.Tensor:
        """Extract coupling scalars from aggregated hidden.

        Args:
            hidden: either (B, 64) pre-aggregated or (E, B, 64) per-expert.
            apply_mask: True = 弱带 ≤0.3 clip 为 0 (调试/特定下游用);
                        False (默认) = 仅 sigmoid, 输出 raw coupling strength,
                        COMM-SHADOW 消费时自行做三带判定 (避免双重 clip 矛盾).

        Returns:
            torch.Tensor (B, 15): coupling scalars ∈ [0, 1].
        """
        if hidden.dim() == 3:
            agg = hidden.mean(dim=0)  # (B, 64)
        elif hidden.dim() == 2:
            agg = hidden
        else:
            raise ValueError(f"hidden must be 2D or 3D, got shape {tuple(hidden.shape)}")
        raw = self.net(agg)  # (B, 15) unconstrained
        sig = torch.sigmoid(raw)
        return _apply_band_mask(sig) if apply_mask else sig


def _apply_band_mask(
    values: torch.Tensor, strong: float = STRONG_THRESHOLD, weak: float = WEAK_THRESHOLD
) -> torch.Tensor:
    """Band-mask: 强带 ≥0.5 保留, 弱带 ≤0.3 置 0, 中间带保留原值.

    与 COMM-SHADOW AgentMailShadow _check_coupling_consistency 三带逻辑对齐.
    """
    out = values.clone()
    out = torch.where(out <= weak, torch.zeros_like(out), out)
    return out


def extract_hook_module_names(drift_net_state_dict_keys: list[str]) -> list[str]:
    """Identify the exact module paths we should register a forward_hook on.

    For NeuralSDE v1_dim64 MoE with 3 experts, each expert's `net.6` layer
    (final Linear from hidden→drift scalar) input is the 64-dim we want.

    Returns list of dotted module names like ["experts.0.net", "experts.1.net", "experts.2.net"].
    """
    experts: list[str] = []
    seen: set[str] = set()
    for key in drift_net_state_dict_keys:
        # match "experts.<idx>.net.<layer>.weight" pattern
        parts = key.split(".")
        if len(parts) >= 3 and parts[0] == "experts" and parts[1].isdigit() and parts[2] == "net":
            mod = f"experts.{parts[1]}.net"
            if mod not in seen:
                seen.add(mod)
                experts.append(mod)
    experts.sort(key=lambda s: int(s.split(".")[1]))
    return experts


def freeze_backbone(module: nn.Module) -> None:
    """Set requires_grad=False on a specific module (e.g. drift_net / diffusion_net).

    SPEC H2: 主体冻结策略不允许微调 drift_net / diffusion_net 权重.
    """
    for p in module.parameters():
        p.requires_grad = False


class NeuralSDEHiddenExtractor:
    """Register forward_hook on NeuralSDE drift_net to capture 64-dim hidden_state.

    用法:
      extractor = NeuralSDEHiddenExtractor(drift_net, device="mps")
      with extractor.capture():
          loss = model.forward(...)
      hidden = extractor.last_hidden  # (E, B, 64)
      # 冻结后只训 head:
      head = DomainCouplingHead().to(device)
      optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3)
      coupling = head(hidden.to(device))
    """

    def __init__(self, drift_net: nn.Module, device: str = "cpu"):
        self.drift_net = drift_net
        self.device = device
        self.last_hidden: Optional[torch.Tensor] = None
        self._hooks: list = []
        self._registered = False

    def register(self) -> None:
        """Discover all expert nets and register one hook per expert.

        Hook fires on the output of the entire expert.net (after net[6]) —
        we actually want the *input* to net[6], so we use `register_forward_hook`
        with `pre_hook=True` on `net[6]` directly.
        """
        if self._registered:
            return
        # 每个 expert.net[6] 是最后一层 Linear(64 → 1); 它的输入是 64-dim hidden.
        self._buffer: list[torch.Tensor] = []

        def _make_hook(idx: int):
            def hook(mod, inp, _out):
                if inp and isinstance(inp[0], torch.Tensor):
                    h = inp[0].detach()  # (B, 64)
                    # 保持顺序: experts.0, .1, .2
                    if idx < len(self._buffer):
                        self._buffer[idx] = h
                    else:
                        self._buffer.append(h)

            return hook

        # 发现 expert 数
        experts = extract_hook_module_names(list(self.drift_net.state_dict().keys()))
        for idx, mod_path in enumerate(experts):
            parent = self.drift_net
            for name in mod_path.split("."):
                parent = getattr(parent, name)
            final_linear = getattr(parent, "6")  # net[6]
            hook_handle = final_linear.register_forward_hook(_make_hook(idx), prepend=True)
            self._hooks.append(hook_handle)
        self._registered = True

    def remove(self) -> None:
        for h in self._hooks:
            h.remove()
        self._hooks = []
        self._registered = False

    def capture(self):
        """Context manager: clear buffer on enter, expose last_hidden on exit."""

        class _Ctx:
            def __enter__(inner):
                self.register()
                self._buffer.clear()
                return self

            def __exit__(inner, *_exc):
                if self._buffer:
                    # pad 到 expert 数 = 3 （对缺失 expert 补零）
                    max_experts = len(self._buffer)
                    if max_experts < 3:
                        zeros = self._buffer[0].detach() * 0
                        self._buffer.extend([zeros] * (3 - max_experts))
                    self.last_hidden = torch.stack(self._buffer, dim=0)  # (E, B, 64)
                    self.last_hidden = self.last_hidden.to(self.device)
                return False

        return _Ctx()


def load_neural_sde_v1_dim64(ckpt_path: str, device: str = "cpu"):
    """Load NeuralSDE v1_dim64 checkpoint and return drift_net + ckpt dict.

    Phase B MVP 只需要 drift_net (hook 点在 MoE 每 expert 的 net.6 输入), diffusion_net
    不加载 (省一步 state_dict 匹配 + 不占 MPS 内存).

    ckpt 结构推断: use_moe=True → drift_net = _MoEDriftNet, 内部 3 个 expert,
    每个 expert.net.6 输入 = 64-dim hidden (就是 DomainCouplingHead hook 目标).
    """
    from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

    ck = torch.load(ckpt_path, map_location=device, weights_only=False)
    hidden_dim = ck.get("hidden_dim", 64)
    sig_dim = ck.get("sig_dim", 15)
    n_regimes = ck.get("n_regimes", 3)
    drift_clip = ck.get("drift_clip", 2.0)
    dropout = ck.get("dropout", 0.05)
    use_cross_attn = ck.get("use_cross_attention", True)
    cross_attn_dim = ck.get("cross_attn_dim", 64)
    cross_attn_heads = ck.get("cross_attn_heads", 8)
    exogenous_factor_dim = ck.get("exogenous_factor_dim", 36)
    exogenous_dim = ck.get("exogenous_dim", 0)
    moe_routing = ck.get("moe_routing", "hard")
    factor_head_mask = ck.get("factor_head_mask")
    use_moe = ck.get("use_moe", True)
    use_transition = ck.get("use_transition", False)
    n_transition = n_regimes if use_transition else 0

    drift_net = _MoEDriftNet(
        n_experts=n_regimes if use_moe else 1,
        hidden_dim=hidden_dim,
        sig_dim=sig_dim,
        clip=drift_clip,
        n_transition=n_transition,
        dropout=dropout,
        routing=moe_routing,
        exogenous_dim=exogenous_dim,
        use_cross_attention=use_cross_attn,
        exogenous_factor_dim=exogenous_factor_dim,
        cross_attn_dim=cross_attn_dim,
        cross_attn_heads=cross_attn_heads,
        factor_head_mask=factor_head_mask,
    )
    drift_net.load_state_dict(ck["drift_net_state_dict"], strict=False)
    drift_net.to(device).eval()
    return drift_net, ck
