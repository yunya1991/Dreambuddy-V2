"""
易经推理引擎 — Yijing Inference Engine。

将易经作为 AI 推理算法实现：
1. 太极 → 两仪 → 四象 → 八卦 → 六十四卦
2. 重卦：内卦（下卦）+ 外卦（上卦）= 六十四卦
3. 爻变：动爻产生变卦，代表事物发展变化
4. 卦辞/爻辞：推理结论，可解释、可追溯

对应交易场景：
- 市场状态 → 卦象（整体格局）
- 价格阶段 → 爻位（当前位置）
- 趋势变化 → 变卦（未来方向）
- 操作策略 → 卦辞/爻辞（行动指南）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from ._constants import (
    GUA_BINARY, BINARY_TO_GUA,
    GUA_QIAN, GUA_KUN, GUA_ZHEN, GUA_XUN,
    GUA_KAN, GUA_LI, GUA_GEN, GUA_DUI,
    DIR_UP, DIR_DOWN, DIR_FLAT, DIR_TRANSITIONING, DIR_UNKNOWN,
    YAO_PROB_ADJUSTMENT_FACTOR, YAO_PROB_MAX,
    YAO_PROB_REVERSAL_BONUS, YAO_PROB_REVERSAL_MAX,
    PHASE_BOUNDARY_LOW, PHASE_BOUNDARY_MID_LOW,
    PHASE_BOUNDARY_MID, PHASE_BOUNDARY_MID_HIGH,
)
from .sixty_four_guas import (
    SIXTY_FOUR_GUAS, HexagramKnowledge, YaoResult,
    get_hexagram_knowledge, build_hexagram_by_guas,
)


@dataclass
class YijingResult:
    """易经推理结果。"""
    # 本卦
    hexagram_name: str = ""
    hexagram_name_cn: str = ""
    inner_gua: str = ""
    outer_gua: str = ""
    gua_ci: str = ""
    xiang_zhuan: str = ""

    # 六爻
    yaos: List[YaoResult] = field(default_factory=list)

    # 动爻
    changing_yaos: List[int] = field(default_factory=list)  # 0-5
    num_changing_yaos: int = 0

    # 变卦
    changed_hexagram_name: str = ""
    changed_hexagram_name_cn: str = ""
    changed_gua_ci: str = ""

    # 推理结论
    overall_meaning: str = ""
    direction_hint: str = DIR_UNKNOWN
    confidence: float = 0.0
    risk_level: str = "medium"

    # 阶段定位
    current_phase: str = ""       # 当前爻位对应的阶段
    development_stage: str = ""   # 发展阶段判断

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hexagram_name": self.hexagram_name,
            "hexagram_name_cn": self.hexagram_name_cn,
            "inner_gua": self.inner_gua,
            "outer_gua": self.outer_gua,
            "gua_ci": self.gua_ci,
            "xiang_zhuan": self.xiang_zhuan,
            "yaos": [y.to_dict() for y in self.yaos],
            "changing_yaos": self.changing_yaos,
            "num_changing_yaos": self.num_changing_yaos,
            "changed_hexagram_name": self.changed_hexagram_name,
            "changed_hexagram_name_cn": self.changed_hexagram_name_cn,
            "changed_gua_ci": self.changed_gua_ci,
            "overall_meaning": self.overall_meaning,
            "direction_hint": self.direction_hint,
            "confidence": round(self.confidence, 4),
            "risk_level": self.risk_level,
            "current_phase": self.current_phase,
            "development_stage": self.development_stage,
        }


def _dummy_hex_knowledge() -> HexagramKnowledge:
    """创建默认 HexagramKnowledge（用于 force 模式无卦象时）。"""
    return HexagramKnowledge(
        name="", name_cn="",
        inner_gua="", outer_gua="",
        gua_ci="", tuan_zhuan="", xiang_zhuan="",
        yao_ci=[],
        direction_hint=DIR_FLAT,
        confidence_base=0.5,
        market_meaning="",
        risk_level="中",
    )


class YijingEngine:
    """
    易经推理引擎。

    双模式运行：
    1. 独立模式（infer）：四维评分 → 卦象（旧模式，兼容）
    2. 解释模式（interpret_force）：力学结果 → 卦象（新模式，符号解释层）

    核心算法：
    1. 从市场数据中提取"阴阳"信号 → 两仪
    2. 两仪组合成四象 → 四象
    3. 四象组合成八卦 → 八卦
    4. 内外卦组合成六十四卦 → 重卦
    5. 识别动爻 → 变卦
    6. 卦辞+爻辞+变卦 → 综合推理结论
    """

    def __init__(self,
                 inner_thresholds: tuple = (0.35, 0.55, 0.65),
                 outer_thresholds: tuple = (0.35, 0.55, 0.65)):
        """
        Args:
            inner_thresholds: 内卦三爻阈值（低/中/高），控制卦象分布
            outer_thresholds: 外卦三爻阈值
        """
        self.inner_thresholds = inner_thresholds
        self.outer_thresholds = outer_thresholds
        self._hexagram_cache: Dict[str, HexagramKnowledge] = {}

    def infer(self,
              supply_demand_score: float,
              technical_score: float,
              capital_flow_score: float,
              sentiment_score: float,
              trend_strength: float = 0.5,
              volatility: float = 0.5,
              volume_ratio: float = 1.0,
              price_position: float = 0.5,
              ma5: float = None,
              ma10: float = None,
              ma20: float = None,
              momentum_direction: str = None,
              close_price: float = None) -> YijingResult:
        """
        从市场指标推理卦象。

        四维评分 → 八卦 → 六十四卦

        Args:
            supply_demand_score: 供需评分（0-1，高=供大于求？不，高=需求旺盛）
            technical_score: 技术面评分（0-1，高=技术向好）
            capital_flow_score: 资金流评分（0-1，高=资金流入）
            sentiment_score: 情绪面评分（0-1，高=情绪乐观）
            trend_strength: 趋势强度（0-1）
            volatility: 波动率（0-1）
            volume_ratio: 量比
            price_position: 价格位置（0-1，0=底部，1=顶部）

        Returns:
            YijingResult
        """
        # Step 1: 四维 → 内卦（下卦，代表内在本质）
        inner_gua = self._compute_inner_gua(
            supply_demand_score, technical_score)

        # Step 2: 四维 → 外卦（上卦，代表外在环境）
        outer_gua = self._compute_outer_gua(
            capital_flow_score, sentiment_score)

        # Step 3: 重卦 → 六十四卦
        hex_name = build_hexagram_by_guas(inner_gua, outer_gua)
        if not hex_name:
            hex_name = self._fallback_hexagram(inner_gua, outer_gua)

        hex_knowledge = get_hexagram_knowledge(hex_name)
        if not hex_knowledge:
            return YijingResult()

        # Step 4: 计算动爻（基于趋势强度、波动率、量比等）
        changing_yaos = self._compute_changing_yaos(
            trend_strength, volatility, volume_ratio, price_position)

        # Step 5: 计算变卦
        changed_hex = self._compute_changed_hexagram(
            inner_gua, outer_gua, changing_yaos)

        # Step 6: 生成六爻结果
        yaos = []
        for i in range(6):
            yao = hex_knowledge.get_yao_result(
                yao_index=i,
                is_changing=(i in changing_yaos),
            )
            yaos.append(yao)

        # Step 7: 综合推理结论
        # 先计算方向（置信度计算依赖方向）
        direction = self._compute_direction(
            hex_knowledge, changed_hex, changing_yaos,
            supply_demand_score, technical_score,
            capital_flow_score, sentiment_score,
            price_position, ma5, ma10, ma20,
            momentum_direction, close_price)

        confidence = self._compute_confidence(
            hex_knowledge, changing_yaos, trend_strength,
            supply_demand_score, technical_score,
            capital_flow_score, sentiment_score,
            direction)

        overall_meaning = self._generate_overall_meaning(
            hex_knowledge, changed_hex, changing_yaos, price_position)

        current_phase = self._determine_phase(price_position)
        dev_stage = self._determine_development_stage(
            hex_knowledge, price_position, changing_yaos)

        return YijingResult(
            hexagram_name=hex_name,
            hexagram_name_cn=hex_knowledge.name_cn,
            inner_gua=inner_gua,
            outer_gua=outer_gua,
            gua_ci=hex_knowledge.gua_ci,
            xiang_zhuan=hex_knowledge.xiang_zhuan,
            yaos=yaos,
            changing_yaos=changing_yaos,
            num_changing_yaos=len(changing_yaos),
            changed_hexagram_name=changed_hex.get("name", ""),
            changed_hexagram_name_cn=changed_hex.get("name_cn", ""),
            changed_gua_ci=changed_hex.get("gua_ci", ""),
            overall_meaning=overall_meaning,
            direction_hint=direction,
            confidence=confidence,
            risk_level=hex_knowledge.risk_level,
            current_phase=current_phase,
            development_stage=dev_stage,
        )

    # ============================================================
    # 符号解释层：从力学结果翻译卦象
    # ============================================================
    def interpret_force(self, force_result,
                        supply_demand_score: float = 0.5,
                        technical_score: float = 0.5,
                        capital_flow_score: float = 0.5,
                        sentiment_score: float = 0.5,
                        volatility: float = 0.5,
                        volume_ratio: float = 1.0,
                        price_position: float = 0.5,
                        trend_strength: float = 0.5) -> YijingResult:
        """
        符号解释层 — 从力学结果翻译卦象。

        力学引擎决定方向和强度，易经引擎负责：
        1. 把力场状态映射为卦象（符号化）
        2. 提供卦辞/爻辞的人文解释
        3. 用变卦描述转折预警

        类似文字大语言模型 — 把物理结果翻译成人话。

        八卦 = 时空表里里的两极：
        - 时之两极：起始(阳) vs 终结(阴) — 趋势时间维度
        - 空之两极：顶(阳) vs 底(阴) — 价格空间维度
        - 表里之两极：实(阳) vs 虚(阴) — 量价能量维度

        Args:
            force_result: ForceEngine 的输出
            其余参数用于补充卦象细节
        """
        forces = force_result.forces

        # --- 内卦（里+表）：内在本质 — 表里之虚实 ---
        # 下爻: 表 (volume_ratio > 1.0 → 实=阳, else 虚=阴)
        # 中爻: 里 (capital_flow_score > 0.5 → 实=阳, else 虚=阴)
        # 上爻: 表里协同 (表力 × 里力 > 0 → 阳, < 0 → 阴)
        inner_gua = self._poles_to_inner_gua(
            volume_ratio=volume_ratio,
            capital_flow_score=capital_flow_score,
            surface_force=forces.surface_force,
            core_force=forces.core_force,
        )

        # --- 外卦（时+空）：外部环境 — 时空之起始/顶底 ---
        # 下爻: 时 (trend_strength > 0.5 → 起始=阳, else 终结=阴)
        # 中爻: 空 (price_position > 0.65 → 顶=阳, < 0.35 → 底=阴, else 用力方向)
        # 上爻: 时空协同 (时力 × 空力 > 0 → 阳, < 0 → 阴)
        outer_gua = self._poles_to_outer_gua(
            trend_strength=trend_strength,
            price_position=price_position,
            time_force=forces.time_force,
            space_force=forces.space_force,
        )

        # --- 动爻：从加速度和转折预警推导 ---
        changing_yaos = self._force_to_changing_yaos(
            force_result.acceleration,
            force_result.reversal_warning,
            force_result.reversal_strength,
            price_position,
        )

        # --- 变卦 ---
        changed_hex = self._compute_changed_hexagram(
            inner_gua, outer_gua, changing_yaos)

        # --- 卦象知识 ---
        hex_name = self._build_hexagram_name(inner_gua, outer_gua)
        hex_knowledge = get_hexagram_knowledge(hex_name)

        # --- 方向：以力学结果为准 ---
        direction = force_result.direction

        # --- 置信度：以力学结果为准，卦象微调 ---
        confidence = force_result.confidence
        # 卦象支持度微调
        if hex_knowledge:
            gua_support = hex_knowledge.confidence_base
            confidence = confidence * 0.8 + gua_support * 0.2

        # --- 整体含义 ---
        overall_meaning = self._force_to_meaning(
            force_result, hex_knowledge, changed_hex)

        # --- 阶段 ---
        current_phase = self._determine_phase(price_position)
        dev_stage = self._determine_development_stage(
            hex_knowledge if hex_knowledge else _dummy_hex_knowledge(),
            price_position, changing_yaos)

        # --- 风险等级 ---
        risk_level = "高" if force_result.reversal_warning else (
            "中" if force_result.trend_strength > 0.6 else "低")

        return YijingResult(
            hexagram_name=hex_name,
            hexagram_name_cn=hex_knowledge.name_cn if hex_knowledge else hex_name,
            inner_gua=inner_gua,
            outer_gua=outer_gua,
            gua_ci=hex_knowledge.gua_ci if hex_knowledge else "",
            xiang_zhuan=hex_knowledge.xiang_zhuan if hex_knowledge else "",
            yaos=[],
            changing_yaos=changing_yaos,
            num_changing_yaos=len(changing_yaos),
            changed_hexagram_name=changed_hex.get("name", ""),
            changed_hexagram_name_cn=changed_hex.get("name_cn", ""),
            changed_gua_ci=changed_hex.get("gua_ci", ""),
            overall_meaning=overall_meaning,
            direction_hint=direction,
            confidence=max(0.0, min(1.0, confidence)),
            risk_level=risk_level,
            current_phase=current_phase,
            development_stage=dev_stage,
        )

    def _poles_to_inner_gua(self,
                             volume_ratio: float,
                             capital_flow_score: float,
                             surface_force,
                             core_force) -> str:
        """
        从表里两极推导内卦。

        内卦 = 表里之虚实：
        - 下爻: 表 (volume_ratio > 1.0 → 实=阳, else 虚=阴)
        - 中爻: 里 (capital_flow_score > 0.5 → 实=阳, else 虚=阴)
        - 上爻: 表里协同 (表力 × 里力 > 0 → 阳, < 0 → 阴)

        3 bit → 8 卦。
        """
        # 下爻：表之虚实（量比>1=放量=实）
        yao_low = 1 if volume_ratio > 1.0 else 0
        # 中爻：里之虚实（资金流入=实）
        yao_mid = 1 if capital_flow_score > 0.5 else 0
        # 上爻：表里协同
        synergy = surface_force.direction * core_force.direction
        if synergy > 0.01:
            yao_high = 1
        elif synergy < -0.01:
            yao_high = 0
        else:
            yao_high = yao_low  # 默认跟下爻

        binary = yao_low | (yao_mid << 1) | (yao_high << 2)
        return BINARY_TO_GUA.get(binary, GUA_KUN)

    def _poles_to_outer_gua(self,
                             trend_strength: float,
                             price_position: float,
                             time_force,
                             space_force) -> str:
        """
        从时空两极推导外卦。

        外卦 = 时空之起始/顶底：
        - 下爻: 时 (trend_strength > 0.5 → 起始=阳, else 终结=阴)
        - 中爻: 空 (price_position > 0.65 → 顶=阳, < 0.35 → 底=阴, else 用力方向)
        - 上爻: 时空协同 (时力 × 空力 > 0 → 阳, < 0 → 阴)

        3 bit → 8 卦。
        """
        from ._constants import (
            BAGUA_POLE_SPACE_HIGH, BAGUA_POLE_SPACE_LOW,
        )

        # 下爻：时之起始/终结
        yao_low = 1 if trend_strength > 0.5 else 0
        # 中爻：空之顶/底
        if price_position > BAGUA_POLE_SPACE_HIGH:
            yao_mid = 1  # 顶
        elif price_position < BAGUA_POLE_SPACE_LOW:
            yao_mid = 0  # 底
        else:
            # 中间区域用力方向判定
            yao_mid = 1 if space_force.direction > 0 else 0
        # 上爻：时空协同
        synergy = time_force.direction * space_force.direction
        if synergy > 0.01:
            yao_high = 1
        elif synergy < -0.01:
            yao_high = 0
        else:
            yao_high = yao_low  # 默认跟下爻

        binary = yao_low | (yao_mid << 1) | (yao_high << 2)
        return BINARY_TO_GUA.get(binary, GUA_KUN)

    def _force_to_changing_yaos(self, acceleration: float,
                                  reversal_warning: bool,
                                  reversal_strength: float,
                                  price_position: float) -> list:
        """
        从加速度推导动爻。

        加速度大 → 变化剧烈 → 动爻多
        转折预警 → 动爻反映转折
        """
        from ._constants import YAO_PROB_OLD_YIN, YAO_PROB_OLD_YANG
        import random as _random

        # 加速度绝对值决定动爻数量倾向
        acc_mag = abs(acceleration)
        base_prob = YAO_PROB_OLD_YIN + YAO_PROB_OLD_YANG  # 0.375
        adjusted_prob = max(0.1, min(YAO_PROB_MAX, base_prob + acc_mag * YAO_PROB_ADJUSTMENT_FACTOR))

        # 转折预警增加动爻概率
        if reversal_warning:
            adjusted_prob = min(YAO_PROB_REVERSAL_MAX, adjusted_prob + YAO_PROB_REVERSAL_BONUS)

        # 主动爻位置（价格位置决定）
        if price_position < PHASE_BOUNDARY_LOW:
            primary_yao = 0
        elif price_position < PHASE_BOUNDARY_MID_LOW:
            primary_yao = 1
        elif price_position < PHASE_BOUNDARY_MID:
            primary_yao = 2
        elif price_position < PHASE_BOUNDARY_MID_HIGH:
            primary_yao = 3
        else:
            primary_yao = 5

        rng = _random.Random(int(acc_mag * 10000 + price_position * 1000))
        changing_yaos = []

        # 主动爻
        if rng.random() < min(0.8, adjusted_prob + 0.2):
            changing_yaos.append(primary_yao)

        # 其余爻
        for yao_idx in range(6):
            if yao_idx in changing_yaos:
                continue
            if rng.random() < adjusted_prob:
                changing_yaos.append(yao_idx)

        # 最多 3 个
        if len(changing_yaos) > 3:
            changing_yaos.sort(key=lambda y: abs(y - primary_yao))
            changing_yaos = sorted(changing_yaos[:3])

        return sorted(set(changing_yaos))

    def _force_to_meaning(self, force_result, hex_knowledge, changed_hex) -> str:
        """从力学结果生成卦象含义。"""
        parts = []

        # 力学描述
        direction_cn = {"UP": "上行", "DOWN": "下行",
                        "FLAT": "震荡", "TRANSITIONING": "转折中",
                        "UNKNOWN": "未知"}.get(force_result.direction, "未知")
        parts.append(f"力学判定：{direction_cn}，趋势强度 {force_result.trend_strength:.2f}")

        # 合力描述
        net_dir = force_result.net_force.direction
        if net_dir > 0.1:
            parts.append(f"合力做多（{net_dir:.2f}）")
        elif net_dir < -0.1:
            parts.append(f"合力做空（{net_dir:.2f}）")
        else:
            parts.append("合力接近均衡，多空对峙")

        # 转折预警
        if force_result.reversal_warning:
            parts.append(f"⚠️ 转折预警：减速 {force_result.reversal_strength:.2f}")

        # 卦象含义
        if hex_knowledge:
            parts.append(f"卦象：{hex_knowledge.name_cn} — {hex_knowledge.gua_ci[:50]}...")

        # 变卦
        if changed_hex and changed_hex.get("name_cn"):
            parts.append(f"变卦：{changed_hex['name_cn']}（趋势演变方向）")

        return "。".join(parts)

    def _build_hexagram_name(self, inner_gua: str, outer_gua: str) -> str:
        """构建六十四卦名。"""
        return build_hexagram_by_guas(inner_gua, outer_gua)

    def _compute_inner_gua(self, sd_score: float, tech_score: float) -> str:
        """
        计算内卦（下卦）— 内在本质：供需 + 技术面。

        用三爻不同阈值，让八卦均匀分布：
        - 初爻：供需（低阈值，敏感）
        - 二爻：技术（中阈值）
        - 三爻：综合（高阈值，确认）
        """
        t_low, t_mid, t_high = self.inner_thresholds
        yao1 = 1 if sd_score > t_low else 0
        yao2 = 1 if tech_score > t_mid else 0
        combined = (sd_score + tech_score) / 2
        yao3 = 1 if combined > t_high else 0

        binary = yao1 | (yao2 << 1) | (yao3 << 2)
        return BINARY_TO_GUA.get(binary, GUA_KUN)

    def _compute_outer_gua(self, cf_score: float, sent_score: float) -> str:
        """
        计算外卦（上卦）— 外在环境：资金流 + 情绪面。

        用三爻不同阈值，让八卦均匀分布。
        """
        t_low, t_mid, t_high = self.outer_thresholds
        yao4 = 1 if cf_score > t_low else 0
        yao5 = 1 if sent_score > t_mid else 0
        combined = (cf_score + sent_score) / 2
        yao6 = 1 if combined > t_high else 0

        binary = yao4 | (yao5 << 1) | (yao6 << 2)
        return BINARY_TO_GUA.get(binary, GUA_KUN)

    def _compute_changing_yaos(self,
                               trend_strength: float,
                               volatility: float,
                               volume_ratio: float,
                               price_position: float,
                               seed: int = None) -> List[int]:
        """
        计算动爻。

        Phase 1 基线：传统易经铜钱法概率
          - 老阴（变）：1/16  → 6
          - 少阳（不变）：5/16 → 7
          - 少阴（不变）：5/16 → 8
          - 老阳（变）：5/16  → 9

        在传统概率基础上，用市场数据（趋势/波动率/量比/价格位置）进行调制，
        使动爻位置和数量与市场状态相关，同时保持传统概率的统计特征。

        返回动爻索引列表（0-5，初爻到上爻）
        """
        from ._constants import (
            YAO_PROB_OLD_YIN, YAO_PROB_SHAO_YANG,
            YAO_PROB_SHAO_YIN, YAO_PROB_OLD_YANG,
        )
        import random as _random

        # 使用 seed 确保可复现（seeded PRNG，P0 决议#7）
        rng = _random.Random(seed) if seed is not None else _random.Random(
            int(trend_strength * 1000 + volatility * 100 +
                volume_ratio * 10 + price_position * 10000))

        # 传统基准变爻概率：老阴 1/16 + 老阳 5/16 = 6/16 = 0.375
        base_changing_prob = YAO_PROB_OLD_YIN + YAO_PROB_OLD_YANG

        # 市场调制因子：将市场状态映射到变爻概率的微调
        # 波动率高 → 变爻概率增加
        # 趋势极强 → 变爻概率减少（趋势明确）
        # 量比异常 → 变爻概率增加
        modulation = 0.0
        modulation += (volatility - 0.5) * 0.3       # 波动率调制
        modulation += (volume_ratio - 1.0) * 0.1      # 量比调制
        modulation -= max(0, trend_strength - 0.7) * 0.2  # 强趋势减少变化

        # 调制后的变爻概率（边界约束 0.1 ~ 0.6）
        adjusted_prob = max(0.1, min(0.6, base_changing_prob + modulation))

        # 价格位置决定主动爻位置
        # 底部 → 初爻动（开始变化）
        # 中部 → 三、四爻动（过程变化）
        # 顶部 → 上爻动（终极变化）
        if price_position < PHASE_BOUNDARY_LOW:
            primary_yao = 0
        elif price_position < PHASE_BOUNDARY_MID_LOW:
            primary_yao = 1
        elif price_position < PHASE_BOUNDARY_MID:
            primary_yao = 2
        elif price_position < PHASE_BOUNDARY_MID_HIGH:
            primary_yao = 3
        else:
            primary_yao = 5

        # 逐爻判定是否为动爻
        changing_yaos = []

        # 主动爻：概率提升
        primary_prob = min(0.8, adjusted_prob + 0.2)
        if rng.random() < primary_prob:
            changing_yaos.append(primary_yao)

        # 其余爻：使用调制后的概率
        for yao_idx in range(6):
            if yao_idx in changing_yaos:
                continue
            # 离主动爻越近，概率略高
            distance = abs(yao_idx - primary_yao)
            yao_prob = adjusted_prob * (1.0 - distance * 0.1)
            if rng.random() < yao_prob:
                changing_yaos.append(yao_idx)

        # 约束：最多 3 个动爻（易经传统最多三爻变）
        if len(changing_yaos) > 3:
            # 保留离主动爻最近的 3 个
            changing_yaos.sort(key=lambda y: abs(y - primary_yao))
            changing_yaos = sorted(changing_yaos[:3])

        return sorted(set(changing_yaos))

    def _compute_changed_hexagram(self,
                                  inner_gua: str,
                                  outer_gua: str,
                                  changing_yaos: List[int]) -> Dict[str, str]:
        """
        计算变卦。

        动爻阴阳反转，得到变卦
        """
        if not changing_yaos:
            return {}

        # 获取本卦的六爻二进制
        inner_bin = GUA_BINARY.get(inner_gua, 0)
        outer_bin = GUA_BINARY.get(outer_gua, 0)
        full_bin = (outer_bin << 3) | inner_bin

        # 反转动爻
        for yao in changing_yaos:
            full_bin ^= (1 << yao)

        # 分解为新的内外卦
        new_inner_bin = full_bin & 0b111
        new_outer_bin = (full_bin >> 3) & 0b111

        new_inner = BINARY_TO_GUA.get(new_inner_bin, GUA_KUN)
        new_outer = BINARY_TO_GUA.get(new_outer_bin, GUA_KUN)

        changed_name = build_hexagram_by_guas(new_inner, new_outer)
        if not changed_name:
            return {"inner_gua": new_inner, "outer_gua": new_outer}

        changed_knowledge = get_hexagram_knowledge(changed_name)
        if not changed_knowledge:
            return {"name": changed_name, "name_cn": ""}

        return {
            "name": changed_name,
            "name_cn": changed_knowledge.name_cn,
            "gua_ci": changed_knowledge.gua_ci,
            "inner_gua": new_inner,
            "outer_gua": new_outer,
        }

    def _compute_confidence(self,
                            hex_knowledge: HexagramKnowledge,
                            changing_yaos: List[int],
                            trend_strength: float,
                            sd_score: float = 0.5,
                            tech_score: float = 0.5,
                            cf_score: float = 0.5,
                            sent_score: float = 0.5,
                            direction: str = None) -> float:
        """
        计算置信度 — 融合多维一致性。

        置信度因子：
        1. 卦象基础置信度
        2. 动爻数量惩罚
        3. 趋势强度加成
        4. 四维评分一致性加成
        5. 方向明确性加成
        """
        base = hex_knowledge.confidence_base

        # 动爻惩罚（在传统概率基线下，2-3 个动爻是正常的，不应过度惩罚）
        num_changing = len(changing_yaos)
        if num_changing == 0:
            yao_factor = 1.0
        elif num_changing == 1:
            yao_factor = 0.95
        elif num_changing == 2:
            yao_factor = 0.90
        elif num_changing == 3:
            yao_factor = 0.82
        else:
            yao_factor = 0.70

        # 趋势强度加成
        trend_factor = 0.6 + 0.4 * min(trend_strength, 1.0)

        # 四维评分一致性：标准差越小，一致性越高
        scores = [sd_score, tech_score, cf_score, sent_score]
        avg = sum(scores) / 4
        variance = sum((s - avg) ** 2 for s in scores) / 4
        consistency = 1.0 - min(variance * 4, 0.5)  # 放大方差影响
        consistency_factor = 0.7 + 0.3 * consistency

        # 方向明确性：UP/DOWN 比 FLAT/TRANSITIONING 更确定
        # 但 FLAT 在 ranging regime 中也是有效信号，不应过度惩罚
        if direction in [DIR_UP, DIR_DOWN]:
            dir_factor = 1.0
        elif direction == DIR_FLAT:
            dir_factor = 0.90  # 提升：FLAT 在震荡市中是有效判断
        else:
            dir_factor = 0.75

        # 评分偏离中性：越偏离 0.5，信号越强
        # 但在 ranging regime（四维评分接近 0.5）时，FLAT 方向的置信度
        # 不应因偏离度低而被过度惩罚
        deviation = abs(avg - 0.5) * 2  # 0-1
        if direction == DIR_FLAT and deviation < 0.2:
            # 震荡市中的 FLAT：偏离度低是合理的，不惩罚
            deviation_factor = 0.95
        else:
            deviation_factor = 0.8 + 0.2 * deviation

        confidence = (base * yao_factor * trend_factor *
                      consistency_factor * dir_factor * deviation_factor)
        return max(0.0, min(1.0, confidence))

    def _compute_direction(self,
                           hex_knowledge: HexagramKnowledge,
                           changed_hex: Dict,
                           changing_yaos: List[int],
                           sd_score: float = 0.5,
                           tech_score: float = 0.5,
                           cf_score: float = 0.5,
                           sent_score: float = 0.5,
                           price_position: float = 0.5,
                           ma5: float = None,
                           ma10: float = None,
                           ma20: float = None,
                           momentum_direction: str = None,
                           close_price: float = None) -> str:
        """
        综合方向推理 — 融合卦象与市场数据。

        推理权重：
        1. 四维评分均值 → 基础方向（权重 0.35）
        2. 均线排列 → 趋势方向（权重 0.25）
        3. 卦象方向_hint → 卦象确认（权重 0.20）
        4. 变卦方向 → 未来转折（权重 0.15）
        5. 动量方向 → 短期确认（权重 0.05）
        """
        scores = []

        # 1. 四维评分 → 基础方向
        avg_score = (sd_score + tech_score + cf_score + sent_score) / 4
        if avg_score > 0.55:
            scores.append((DIR_UP, 0.35))
        elif avg_score < 0.45:
            scores.append((DIR_DOWN, 0.35))
        else:
            scores.append((DIR_FLAT, 0.35))

        # 2. 均线排列 → 趋势方向
        if ma5 is not None and ma10 is not None and ma20 is not None:
            if ma5 > ma10 > ma20:
                scores.append((DIR_UP, 0.25))
            elif ma5 < ma10 < ma20:
                scores.append((DIR_DOWN, 0.25))
            else:
                scores.append((DIR_FLAT, 0.25))
        else:
            # 无均线数据时用价格位置推断
            if price_position > 0.6:
                scores.append((DIR_UP, 0.25))
            elif price_position < 0.4:
                scores.append((DIR_DOWN, 0.25))
            else:
                scores.append((DIR_FLAT, 0.25))

        # 3. 卦象方向
        base_dir = hex_knowledge.direction_hint
        if base_dir in [DIR_UP, DIR_DOWN, DIR_FLAT]:
            scores.append((base_dir, 0.20))
        else:
            scores.append((DIR_FLAT, 0.20))

        # 4. 变卦方向
        if changing_yaos and changed_hex:
            changed_knowledge = get_hexagram_knowledge(
                changed_hex.get("name", ""))
            if changed_knowledge:
                changed_dir = changed_knowledge.direction_hint
                if changed_dir in [DIR_UP, DIR_DOWN]:
                    # 本卦与变卦方向不一致 → 转折信号
                    if base_dir in [DIR_UP, DIR_DOWN] and changed_dir != base_dir:
                        scores.append((DIR_TRANSITIONING, 0.15))
                    else:
                        scores.append((changed_dir, 0.15))
                else:
                    scores.append((DIR_FLAT, 0.15))
            else:
                scores.append((DIR_FLAT, 0.15))
        else:
            scores.append((DIR_FLAT, 0.15))

        # 5. 动量方向
        if momentum_direction:
            mom_dir = DIR_UP if momentum_direction.upper() == "UP" else DIR_DOWN
            scores.append((mom_dir, 0.05))
        else:
            scores.append((DIR_FLAT, 0.05))

        # 加权投票
        up_weight = sum(w for d, w in scores if d == DIR_UP)
        down_weight = sum(w for d, w in scores if d == DIR_DOWN)
        trans_weight = sum(w for d, w in scores if d == DIR_TRANSITIONING)
        flat_weight = sum(w for d, w in scores if d == DIR_FLAT)

        # 如果转折信号强，优先返回转折
        if trans_weight > 0.1 and abs(up_weight - down_weight) < 0.15:
            return DIR_TRANSITIONING

        if up_weight > down_weight and up_weight > flat_weight:
            return DIR_UP
        elif down_weight > up_weight and down_weight > flat_weight:
            return DIR_DOWN
        else:
            return DIR_FLAT

    def _generate_overall_meaning(self,
                                  hex_knowledge: HexagramKnowledge,
                                  changed_hex: Dict,
                                  changing_yaos: List[int],
                                  price_position: float) -> str:
        """生成整体含义描述。"""
        parts = []

        parts.append(f"本卦为{hex_knowledge.name_cn}，{hex_knowledge.market_meaning}。")
        parts.append(f"卦辞：{hex_knowledge.gua_ci}")

        if changing_yaos:
            yao_names = [f"第{y+1}爻" for y in changing_yaos]
            parts.append(f"动爻：{'、'.join(yao_names)}，共{len(changing_yaos)}爻动。")

            for y in changing_yaos[:2]:  # 最多显示两个动爻的爻辞
                yao = hex_knowledge.get_yao_result(y, True)
                parts.append(f"  {yao.yao_name}：{yao.yao_ci}")

            if changed_hex.get("name_cn"):
                parts.append(f"变卦为{changed_hex['name_cn']}，代表未来发展趋势。")
                if changed_hex.get("gua_ci"):
                    parts.append(f"变卦卦辞：{changed_hex['gua_ci']}")

        # 阶段判断
        if price_position < 0.3:
            parts.append("当前处于行情初期阶段，宜观察蓄势。")
        elif price_position < 0.7:
            parts.append("当前处于行情中期阶段，宜顺势而为。")
        else:
            parts.append("当前处于行情末期阶段，宜警惕风险。")

        return " ".join(parts)

    def _determine_phase(self, price_position: float) -> str:
        """确定当前阶段。"""
        if price_position < 0.167:
            return "初爻阶段（潜龙勿用）"
        elif price_position < 0.333:
            return "二爻阶段（见龙在田）"
        elif price_position < 0.5:
            return "三爻阶段（终日乾乾）"
        elif price_position < 0.667:
            return "四爻阶段（或跃在渊）"
        elif price_position < 0.833:
            return "五爻阶段（飞龙在天）"
        else:
            return "上爻阶段（亢龙有悔）"

    def _determine_development_stage(self,
                                     hex_knowledge: HexagramKnowledge,
                                     price_position: float,
                                     changing_yaos: List[int]) -> str:
        """
        判断发展阶段。

        基于卦象 + 价格位置 + 动爻：
        - 萌芽期：底部 + 初爻动
        - 成长期：中下部 + 二三爻动
        - 成熟期：中部 + 四五爻动
        - 衰退期：顶部 + 上爻动
        """
        direction = hex_knowledge.direction_hint

        if price_position < 0.3:
            if direction in [DIR_UP, DIR_TRANSITIONING]:
                return "萌芽期（底部酝酿）"
            else:
                return "衰退末期（下跌尾声）"
        elif price_position < 0.5:
            if direction == DIR_UP:
                return "成长期（上升初期）"
            elif direction == DIR_DOWN:
                return "衰退初期（下跌初期）"
            else:
                return "震荡期（方向不明）"
        elif price_position < 0.7:
            if direction == DIR_UP:
                return "成熟期（上升中期）"
            elif direction == DIR_DOWN:
                return "衰退中期（下跌中期）"
            else:
                return "震荡期（方向选择）"
        else:
            if direction in [DIR_UP, DIR_TRANSITIONING]:
                return "鼎盛期（顶部区域）"
            else:
                return "崩溃期（加速下跌）"

    def _fallback_hexagram(self, inner_gua: str, outer_gua: str) -> str:
        """备用卦象生成（如果不在64卦库中）。"""
        # 使用一个简单的映射
        fallback_map = {
            (GUA_QIAN, GUA_QIAN): "qian",
            (GUA_KUN, GUA_KUN): "kun",
            (GUA_ZHEN, GUA_KAN): "zhun",
            (GUA_GEN, GUA_KAN): "meng",
            (GUA_QIAN, GUA_KAN): "xu",
            (GUA_KAN, GUA_QIAN): "song",
            (GUA_KAN, GUA_KUN): "shi",
            (GUA_KUN, GUA_KAN): "bi",
        }
        key = (inner_gua, outer_gua)
        return fallback_map.get(key, "qian")

    def get_hexagram_by_name(self, name: str) -> Optional[HexagramKnowledge]:
        """根据名称获取卦象知识。"""
        return get_hexagram_knowledge(name)

    def get_all_hexagrams(self) -> List[str]:
        """获取所有卦象名称。"""
        return list(SIXTY_FOUR_GUAS.keys())

    # ============================================================
    # 传统起卦方法（用于模拟/测试）
    # ============================================================
    def cast_coin_hexagram(self, coin_results: List[int]) -> Tuple[str, List[int]]:
        """
        铜钱起卦法。

        三枚铜钱，每爻结果：
        - 3正 = 老阳（动爻）→ 9
        - 2正1反 = 少阳 → 7
        - 1正2反 = 少阴 → 8
        - 3反 = 老阴（动爻）→ 6

        Args:
            coin_results: 6组三枚铜钱结果，每组3个0/1（1=正，0=反）

        Returns:
            (卦名, 动爻索引列表)
        """
        yaos_binary = []
        changing = []

        for i, coins in enumerate(coin_results[:6]):
            heads = sum(coins)
            if heads == 3:
                yaos_binary.append(1)  # 老阳（本卦为阳）
                changing.append(i)
            elif heads == 2:
                yaos_binary.append(1)  # 少阳
            elif heads == 1:
                yaos_binary.append(0)  # 少阴
            else:
                yaos_binary.append(0)  # 老阴（本卦为阴）
                changing.append(i)

        # 组装内外卦
        inner_bin = yaos_binary[0] | (yaos_binary[1] << 1) | (yaos_binary[2] << 2)
        outer_bin = yaos_binary[3] | (yaos_binary[4] << 1) | (yaos_binary[5] << 2)

        inner = BINARY_TO_GUA.get(inner_bin, GUA_KUN)
        outer = BINARY_TO_GUA.get(outer_bin, GUA_KUN)

        hex_name = build_hexagram_by_guas(inner, outer) or "qian"
        return hex_name, changing
