"""
辩证ML引擎 — 力学引擎的算法升级

理论映射 (BCRM 力学引擎 → LightGBM):
  对立统一 → 多分类模型 (UP/DOWN/FLAT)，输出双方力量对比概率
  量变质变 → 置信度 = 质变发生的概率
  否定之否定 → Meta-Labeling二级裁决，对第一层信号进行否定/肯定

卦象映射器:
  ML输出 → 卦象解释 → 保留理论可解释性
  不做决策引擎，做可解释层 (Interpretation Layer)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
import json
import os

_lgb = None


def _get_lgb():
    global _lgb
    if _lgb is None:
        import lightgbm as lgb
        _lgb = lgb
    return _lgb


# ============================================================
# 卦象映射器 (Hexagram Interpreter)
# ============================================================

# 八卦-特征维度映射（用于从特征重要性推导主卦）
GUA_DIMENSION_MAP = {
    "qian": {"name": "乾", "trigram": "☰", "element": "天", "nature": "健",
             "description": "趋势强劲，如天之健行不息"},
    "kun": {"name": "坤", "trigram": "☷", "element": "地", "nature": "顺",
            "description": "支撑稳固，如地之厚德载物"},
    "zhen": {"name": "震", "trigram": "☳", "element": "雷", "nature": "动",
             "description": "动量突破，如雷之震动奋发"},
    "xun": {"name": "巽", "trigram": "☴", "element": "风", "nature": "入",
            "description": "波动变化，如风之无孔不入"},
    "kan": {"name": "坎", "trigram": "☵", "element": "水", "nature": "陷",
            "description": "资金流动，如水之润下流通"},
    "li": {"name": "离", "trigram": "☲", "element": "火", "nature": "丽",
           "description": "形态明朗，如火之光明照耀"},
    "gen": {"name": "艮", "trigram": "☶", "element": "山", "nature": "止",
            "description": "结构稳定，如山之静止不动"},
    "dui": {"name": "兑", "trigram": "☱", "element": "泽", "nature": "悦",
            "description": "多周期共振，如两泽相通相悦"},
}

# 64卦简表 (上卦 + 下卦 → 卦名)
SIXTY_FOUR_GUAS = {
    # 乾为天系列
    ("qian", "qian"): {"name": "乾为天", "meaning": "元亨利贞，天行健", "direction": "long"},
    ("qian", "kun"): {"name": "天地否", "meaning": "闭塞不通，小人道长", "direction": "short"},
    ("qian", "zhen"): {"name": "天雷无妄", "meaning": "无妄之福，守正则吉", "direction": "long"},
    ("qian", "xun"): {"name": "天风姤", "meaning": "女壮勿用取女", "direction": "short"},
    ("qian", "kan"): {"name": "天水讼", "meaning": "争讼不利，中和为贵", "direction": "neutral"},
    ("qian", "li"): {"name": "天火同人", "meaning": "同人于野，利涉大川", "direction": "long"},
    ("qian", "gen"): {"name": "天山遁", "meaning": "退避隐遁，以退为进", "direction": "short"},
    ("qian", "dui"): {"name": "天泽履", "meaning": "履虎尾，慎行不咥", "direction": "long"},
    # 坤为地系列
    ("kun", "qian"): {"name": "地天泰", "meaning": "小往大来，吉亨", "direction": "long"},
    ("kun", "kun"): {"name": "坤为地", "meaning": "厚德载物，柔顺利贞", "direction": "neutral"},
    ("kun", "zhen"): {"name": "地雷复", "meaning": "一阳来复，反复其道", "direction": "long"},
    ("kun", "xun"): {"name": "地风升", "meaning": "积小高大，步步高升", "direction": "long"},
    ("kun", "kan"): {"name": "地水师", "meaning": "师出以律，否臧凶", "direction": "short"},
    ("kun", "li"): {"name": "地火明夷", "meaning": "明入地中，韬光养晦", "direction": "short"},
    ("kun", "gen"): {"name": "地山谦", "meaning": "谦尊而光，君子有终", "direction": "neutral"},
    ("kun", "dui"): {"name": "地泽临", "meaning": "以上临下，教思无穷", "direction": "long"},
    # 震为雷系列
    ("zhen", "qian"): {"name": "雷天大壮", "meaning": "大壮利贞，正大光明", "direction": "long"},
    ("zhen", "kun"): {"name": "雷地豫", "meaning": "豫顺以动，利建侯行师", "direction": "long"},
    ("zhen", "zhen"): {"name": "震为雷", "meaning": "洊雷震，恐惧修省", "direction": "long"},
    ("zhen", "xun"): {"name": "雷风恒", "meaning": "恒久而不已，利有攸往", "direction": "long"},
    ("zhen", "kan"): {"name": "雷水解", "meaning": "解险以动，赦过宥罪", "direction": "long"},
    ("zhen", "li"): {"name": "雷火丰", "meaning": "丰大也，日中则昃", "direction": "long"},
    ("zhen", "gen"): {"name": "雷山小过", "meaning": "小过亨，飞鸟遗之音", "direction": "short"},
    ("zhen", "dui"): {"name": "雷泽归妹", "meaning": "归妹，天地之大义也", "direction": "short"},
    # 巽为风系列
    ("xun", "qian"): {"name": "风天小畜", "meaning": "小畜亨，密云不雨", "direction": "neutral"},
    ("xun", "kun"): {"name": "风地观", "meaning": "观盥而不荐，有孚颙若", "direction": "neutral"},
    ("xun", "zhen"): {"name": "风雷益", "meaning": "益损上益下，民说无疆", "direction": "long"},
    ("xun", "xun"): {"name": "巽为风", "meaning": "随风巽，申命行事", "direction": "long"},
    ("xun", "kan"): {"name": "风水涣", "meaning": "涣亨，王假有庙", "direction": "short"},
    ("xun", "li"): {"name": "风火家人", "meaning": "家人利女贞，正家道也", "direction": "long"},
    ("xun", "gen"): {"name": "风山渐", "meaning": "渐女归吉，利贞", "direction": "long"},
    ("xun", "dui"): {"name": "风泽中孚", "meaning": "中孚豚鱼，信及豚鱼", "direction": "long"},
    # 坎为水系列
    ("kan", "qian"): {"name": "水天需", "meaning": "需有孚，光亨贞吉", "direction": "long"},
    ("kan", "kun"): {"name": "水地比", "meaning": "比吉，比之自内", "direction": "long"},
    ("kan", "zhen"): {"name": "水雷屯", "meaning": "屯元亨利贞，刚柔始交", "direction": "neutral"},
    ("kan", "xun"): {"name": "水风井", "meaning": "井改邑不改井，无丧无得", "direction": "neutral"},
    ("kan", "kan"): {"name": "坎为水", "meaning": "习坎有孚维心亨", "direction": "short"},
    ("kan", "li"): {"name": "水火既济", "meaning": "既济亨小，初吉终乱", "direction": "short"},
    ("kan", "gen"): {"name": "水山蹇", "meaning": "蹇难也，利见大人", "direction": "short"},
    ("kan", "dui"): {"name": "水泽节", "meaning": "节亨，苦节不可贞", "direction": "neutral"},
    # 离为火系列
    ("li", "qian"): {"name": "火天大有", "meaning": "大有元亨，火在天上", "direction": "long"},
    ("li", "kun"): {"name": "火地晋", "meaning": "晋康侯用锡马蕃庶", "direction": "long"},
    ("li", "zhen"): {"name": "火雷噬嗑", "meaning": "噬嗑亨，利用狱", "direction": "long"},
    ("li", "xun"): {"name": "火风鼎", "meaning": "鼎元吉亨，革故鼎新", "direction": "long"},
    ("li", "kan"): {"name": "火水未济", "meaning": "未济亨，小狐汔济", "direction": "neutral"},
    ("li", "li"): {"name": "离为火", "meaning": "明两作离，继明照四方", "direction": "long"},
    ("li", "gen"): {"name": "火山旅", "meaning": "旅小亨，旅贞吉", "direction": "short"},
    ("li", "dui"): {"name": "火泽睽", "meaning": "睽小事吉，异中求同", "direction": "short"},
    # 艮为山系列
    ("gen", "qian"): {"name": "山天大畜", "meaning": "大畜利贞，不家食吉", "direction": "long"},
    ("gen", "kun"): {"name": "山地剥", "meaning": "剥不利有攸往，小人长", "direction": "short"},
    ("gen", "zhen"): {"name": "山雷颐", "meaning": "颐贞吉，观颐自求口实", "direction": "neutral"},
    ("gen", "xun"): {"name": "山风蛊", "meaning": "蛊元亨，涉大川", "direction": "short"},
    ("gen", "kan"): {"name": "山水蒙", "meaning": "蒙亨，匪我求童蒙", "direction": "short"},
    ("gen", "li"): {"name": "山火贲", "meaning": "贲亨，小利有攸往", "direction": "long"},
    ("gen", "gen"): {"name": "艮为山", "meaning": "兼山艮，思不出其位", "direction": "neutral"},
    ("gen", "dui"): {"name": "山泽损", "meaning": "损有孚，元吉无咎", "direction": "short"},
    # 兑为泽系列
    ("dui", "qian"): {"name": "泽天夬", "meaning": "夬扬于王庭，孚号有厉", "direction": "long"},
    ("dui", "kun"): {"name": "泽地萃", "meaning": "萃亨，王假有庙", "direction": "long"},
    ("dui", "zhen"): {"name": "泽雷随", "meaning": "随元亨利贞，无咎", "direction": "long"},
    ("dui", "xun"): {"name": "泽风大过", "meaning": "大过栋桡，利有攸往", "direction": "short"},
    ("dui", "kan"): {"name": "泽水困", "meaning": "困亨，贞大人吉", "direction": "short"},
    ("dui", "li"): {"name": "泽火革", "meaning": "革己日乃孚，元亨", "direction": "long"},
    ("dui", "gen"): {"name": "泽山咸", "meaning": "咸亨，利贞取女吉", "direction": "long"},
    ("dui", "dui"): {"name": "兑为泽", "meaning": "丽泽兑，朋友讲习", "direction": "long"},
}


class HexagramMapper:
    """
    卦象映射器 — 将ML输出映射为易经卦象解释 (增强版)

    定位: 可解释层 (Interpretation Layer)
    不做决策，只做"ML输出的人类可读翻译"

    增强功能:
      - 爻位计算: 六爻各有阴阳，对应多空力量的强弱分布
      - 卦辞/象辞/爻辞: 详细的语义解释
      - 互卦: 矛盾内部的深层结构 (2-5爻)
      - 变卦: 矛盾的对立面 (最强力量反转后的卦象)
      - 卦象强度: 偏离均值的程度，对应"矛盾激化程度"
    """

    def __init__(self, feature_names_by_gua: Dict[str, List[str]]):
        self.feature_names_by_gua = feature_names_by_gua
        self.guas = list(GUA_DIMENSION_MAP.keys())
        self._feature_stats = None  # 用于归一化: (mean, std) per feature

    def fit_feature_stats(self, X: np.ndarray, feature_names: List[str]):
        """用训练集统计量做特征归一化基准"""
        means = np.mean(X, axis=0)
        stds = np.std(X, axis=0)
        stds = np.where(stds < 1e-8, 1.0, stds)
        self._feature_stats = {"mean": means, "std": stds, "names": feature_names}

    def predict_gua(
        self,
        feature_values: np.ndarray,
        feature_names: List[str],
        model_direction: int,
        model_confidence: float,
    ) -> Dict[str, Any]:
        """
        根据特征值和ML预测，推导当前卦象

        卦象映射逻辑:
          1. 对每个卦的特征做归一化（z-score），消除量纲差异
          2. 计算每个卦的"活跃度" = 归一化后特征的绝对平均
          3. 活跃度最高的两个卦分别为上卦、下卦
          4. 上卦+下卦 → 64卦卦名 → 卦义解释

        Args:
            feature_values: 单样本特征值向量
            feature_names: 特征名列表
            model_direction: ML预测方向 (1=UP, -1=DOWN, 0=FLAT)
            model_confidence: ML置信度 (0-1)

        Returns:
            卦象解释字典
        """
        # 特征归一化 (z-score)
        if self._feature_stats is not None:
            norm_vals = (feature_values - self._feature_stats["mean"]) / self._feature_stats["std"]
        else:
            norm_vals = feature_values.copy()

        # 计算各卦维度的活跃度（归一化后特征的绝对平均 → 偏离均值的程度）
        # 只对八卦维度计算活跃度，cross_asset等非八卦维度不参与卦象推导
        gua_activity = {}
        for gua, feat_names in self.feature_names_by_gua.items():
            if gua not in GUA_DIMENSION_MAP:
                continue  # 跳过非八卦维度 (如cross_asset)
            indices = [i for i, fn in enumerate(feature_names) if fn in feat_names]
            if indices:
                vals = np.abs(norm_vals[indices])
                gua_activity[gua] = float(np.mean(vals))
            else:
                gua_activity[gua] = 0.0

        # 排序取活跃度最高的两个维度作为上下卦
        # 上卦 = 最活跃的维度（主导力量）
        # 下卦 = 次活跃的维度（次要力量/基础）
        sorted_guas = sorted(gua_activity.items(), key=lambda x: x[1], reverse=True)
        upper_gua = sorted_guas[0][0] if len(sorted_guas) > 0 else "qian"
        lower_gua = sorted_guas[1][0] if len(sorted_guas) > 1 else "kun"
        gua_strengths = gua_activity

        # 查64卦
        gua_key = (upper_gua, lower_gua)
        gua_info = SIXTY_FOUR_GUAS.get(
            gua_key,
            {"name": "未命名卦", "meaning": "力量格局待解", "direction": "neutral"}
        )

        # 方向校准: 如果ML方向与卦义方向不一致，用ML方向为准，卦义提供背景
        direction_consistent = (
            (model_direction == 1 and gua_info["direction"] == "long") or
            (model_direction == -1 and gua_info["direction"] == "short") or
            (model_direction == 0 and gua_info["direction"] == "neutral")
        )

        # 计算六爻 (上下卦各三爻)
        # 爻位: 初爻(下卦初)→二爻(下卦中)→三爻(下卦上)→四爻(上卦初)→五爻(上卦中)→上爻(上卦上)
        # 阳爻=看多/力量强, 阴爻=看空/力量弱
        # 每个卦的三爻对应: 初爻=该维度的短期动量, 二爻=中期趋势, 三爻=长期结构
        hexagram_lines = self._compute_hexagram_lines(
            upper_gua, lower_gua, gua_activity, norm_vals, feature_names,
            model_direction, model_confidence
        )

        # 计算互卦 (2-5爻, 矛盾内部的深层结构)
        mutual_gua = self._compute_mutual_gua(hexagram_lines)

        # 计算变卦 (最强力量反转后的卦象, 矛盾的对立面)
        changed_gua = self._compute_changed_gua(hexagram_lines, gua_activity)

        # 卦象强度 (整体偏离均值的程度 = 矛盾激化程度)
        gua_intensity = float(np.mean(list(gua_activity.values()))) if gua_activity else 0.0

        # 修复: 卦象强度与方向一致性联动 (2026-07-13)
        # 如果方向不一致，卦象强度减半，表示卦象的可解释性降低
        if not direction_consistent:
            gua_intensity *= 0.5

        # 生成解释
        direction_text = "看涨" if model_direction == 1 else (
            "看跌" if model_direction == -1 else "观望"
        )
        confidence_pct = f"{model_confidence * 100:.0f}%"

        interpretation = {
            "upper_gua": GUA_DIMENSION_MAP[upper_gua],
            "lower_gua": GUA_DIMENSION_MAP[lower_gua],
            "hexagram_name": gua_info["name"],
            "hexagram_meaning": gua_info["meaning"],
            "hexagram_direction": gua_info["direction"],
            "ml_direction": direction_text,
            "ml_confidence": confidence_pct,
            "direction_consistent": direction_consistent,
            "gua_strengths": {g: round(s, 4) for g, s in gua_strengths.items()},
            "dominant_dimensions": [
                {"gua": GUA_DIMENSION_MAP[sorted_guas[i][0]]["name"],
                 "trigram": GUA_DIMENSION_MAP[sorted_guas[i][0]]["trigram"],
                 "strength": round(sorted_guas[i][1], 4)}
                for i in range(min(4, len(sorted_guas)))
            ],
            # 增强: 六爻
            "hexagram_lines": hexagram_lines,
            # 增强: 互卦 (矛盾内部深层结构)
            "mutual_gua": mutual_gua,
            # 增强: 变卦 (矛盾对立面)
            "changed_gua": changed_gua,
            # 增强: 卦象强度 (矛盾激化程度)
            "gua_intensity": round(gua_intensity, 4),
            "narrative": self._generate_narrative(
                gua_info, direction_text, confidence_pct,
                direction_consistent, sorted_guas, hexagram_lines,
                mutual_gua, changed_gua, gua_intensity
            ),
        }

        return interpretation

    def _compute_hexagram_lines(
        self,
        upper_gua: str,
        lower_gua: str,
        gua_activity: Dict[str, float],
        norm_vals: np.ndarray,
        feature_names: List[str],
        model_direction: int,
        model_confidence: float,
    ) -> List[Dict]:
        """
        计算六爻 (上下卦各三爻)

        爻位映射:
          下卦三爻 (内卦, 内在因素):
            初爻 (位1): 短期动量/即时力量 (该卦维度的短期特征)
            二爻 (位2): 中期趋势/核心力量 (该卦维度的中期特征)
            三爻 (位3): 长期结构/基础力量 (该卦维度的长期特征)
          上卦三爻 (外卦, 外在因素):
            四爻 (位4): 短期外部影响
            五爻 (位5): 中期外部趋势
            上爻 (位6): 长期外部结构

        阴阳判定:
          阳爻 (━): 该爻位力量 > 中位数阈值，看多/力量强
          阴爻 (╶╴): 该爻位力量 < 中位数阈值，看空/力量弱
        """
        lines = []

        # 下卦三爻 (内卦)
        lower_activity = gua_activity.get(lower_gua, 0.5)
        for pos in range(3):  # 0=初, 1=二, 2=三
            # 初爻: 短期波动 (高权重)
            # 二爻: 中期趋势 (中权重)
            # 三爻: 长期结构 (低权重)
            weight = [1.2, 1.0, 0.8][pos]
            strength = lower_activity * weight
            is_yang = (model_direction > 0 and strength > 0.3) or (model_direction < 0 and strength < 0.5)
            # 简化: 以活跃度为基础, 结合ML方向判定阴阳
            # 活跃度越高, 力量越强; ML方向为正, 阳爻概率越大
            yang_prob = 0.5 + (model_direction * 0.3) + (strength - 0.5) * 0.4
            is_yang = yang_prob > 0.5

            line_name = ["初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]
            line_type = "阳" if is_yang else "阴"
            line_symbol = "━" if is_yang else "╶╴"
            lines.append({
                "position": pos + 1,
                "name": line_name[pos],
                "type": line_type,
                "symbol": line_symbol,
                "strength": round(strength, 4),
                "yang_prob": round(min(1.0, max(0.0, yang_prob)), 4),
                "gua_part": "lower",
            })

        # 上卦三爻 (外卦)
        upper_activity = gua_activity.get(upper_gua, 0.5)
        for pos in range(3):  # 0=四, 1=五, 2=上
            weight = [1.2, 1.0, 0.8][pos]
            strength = upper_activity * weight
            yang_prob = 0.5 + (model_direction * 0.3) + (strength - 0.5) * 0.4
            is_yang = yang_prob > 0.5

            line_name = ["初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]
            line_type = "阳" if is_yang else "阴"
            line_symbol = "━" if is_yang else "╶╴"
            lines.append({
                "position": pos + 4,
                "name": line_name[pos + 3],
                "type": line_type,
                "symbol": line_symbol,
                "strength": round(strength, 4),
                "yang_prob": round(min(1.0, max(0.0, yang_prob)), 4),
                "gua_part": "upper",
            })

        return lines

    def _compute_mutual_gua(self, hexagram_lines: List[Dict]) -> Dict:
        """
        计算互卦 (矛盾内部的深层结构)

        互卦取法: 取2、3、4爻为下互卦, 3、4、5爻为上互卦
        含义: 事物发展过程中内部的深层矛盾结构
        """
        if len(hexagram_lines) < 6:
            return {"name": "未知", "lines": []}

        # 2-4爻为下互卦 (索引1-3)
        lower_mutual_lines = [hexagram_lines[1], hexagram_lines[2], hexagram_lines[3]]
        # 3-5爻为上互卦 (索引2-4)
        upper_mutual_lines = [hexagram_lines[2], hexagram_lines[3], hexagram_lines[4]]

        lower_mutual_gua = self._lines_to_trigram(lower_mutual_lines)
        upper_mutual_gua = self._lines_to_trigram(upper_mutual_lines)

        gua_key = (upper_mutual_gua, lower_mutual_gua)
        gua_info = SIXTY_FOUR_GUAS.get(
            gua_key,
            {"name": "未命名互卦", "meaning": "内部结构待解", "direction": "neutral"}
        )

        return {
            "upper_gua": GUA_DIMENSION_MAP.get(upper_mutual_gua, {}),
            "lower_gua": GUA_DIMENSION_MAP.get(lower_mutual_gua, {}),
            "name": gua_info["name"],
            "meaning": gua_info["meaning"],
            "direction": gua_info["direction"],
            "lines_symbol": self._lines_to_symbol([l for l in lower_mutual_lines] + [l for l in upper_mutual_lines]),
        }

    def _compute_changed_gua(self, hexagram_lines: List[Dict], gua_activity: Dict[str, float]) -> Dict:
        """
        计算变卦 (矛盾的对立面)

        变卦取法: 最活跃的爻发生变化 (阳变阴, 阴变阳)
        含义: 事物发展到极点后的对立面, 即"物极必反"
        """
        if len(hexagram_lines) < 6:
            return {"name": "未知", "changed_line": None}

        # 找到力量最强的爻 (最可能发生变化)
        max_strength_idx = max(range(6), key=lambda i: hexagram_lines[i]["strength"])
        changed_line = hexagram_lines[max_strength_idx].copy()

        # 阴阳反转
        new_type = "阴" if changed_line["type"] == "阳" else "阳"
        new_symbol = "╶╴" if changed_line["type"] == "阳" else "━"
        changed_line["new_type"] = new_type
        changed_line["new_symbol"] = new_symbol

        # 构建变卦的六爻
        changed_lines = [l.copy() for l in hexagram_lines]
        changed_lines[max_strength_idx]["type"] = new_type
        changed_lines[max_strength_idx]["symbol"] = new_symbol

        # 解析变卦的上下卦
        lower_changed = self._lines_to_trigram(changed_lines[:3])
        upper_changed = self._lines_to_trigram(changed_lines[3:])

        gua_key = (upper_changed, lower_changed)
        gua_info = SIXTY_FOUR_GUAS.get(
            gua_key,
            {"name": "未命名变卦", "meaning": "变化方向待解", "direction": "neutral"}
        )

        return {
            "name": gua_info["name"],
            "meaning": gua_info["meaning"],
            "direction": gua_info["direction"],
            "changed_line_name": changed_line["name"],
            "changed_line_pos": changed_line["position"],
            "original_type": changed_line["type"],
            "new_type": new_type,
            "lines_symbol": self._lines_to_symbol(changed_lines),
        }

    def _lines_to_trigram(self, lines: List[Dict]) -> str:
        """将三爻转换为八卦名称 (从下到上)"""
        if len(lines) < 3:
            return "qian"

        # 八卦对应表 (从下到上: 初、二、三)
        # 0=阴, 1=阳
        trigram_map = {
            (1, 1, 1): "qian",   # 乾 ☰
            (0, 0, 0): "kun",    # 坤 ☷
            (1, 0, 0): "zhen",   # 震 ☳
            (0, 1, 1): "xun",    # 巽 ☴
            (0, 1, 0): "kan",    # 坎 ☵
            (1, 0, 1): "li",     # 离 ☲
            (0, 0, 1): "gen",    # 艮 ☶
            (1, 1, 0): "dui",    # 兑 ☱
        }

        line_types = tuple(1 if l["type"] == "阳" else 0 for l in lines)
        return trigram_map.get(line_types, "qian")

    def _lines_to_symbol(self, lines: List[Dict]) -> str:
        """将六爻转换为符号字符串 (从上到下显示)"""
        # 从上到下显示: 上爻→初爻 (与数组顺序相反)
        reversed_lines = list(reversed(lines))
        return "\n".join([f"  {l['symbol']}" for l in reversed_lines])

    def _generate_narrative(
        self,
        gua_info: Dict,
        direction_text: str,
        confidence_pct: str,
        consistent: bool,
        sorted_guas: List[Tuple[str, float]],
        hexagram_lines: Optional[List[Dict]] = None,
        mutual_gua: Optional[Dict] = None,
        changed_gua: Optional[Dict] = None,
        gua_intensity: float = 0.0,
    ) -> str:
        """生成人类可读的卦象叙事 (增强版)"""
        top2_names = [GUA_DIMENSION_MAP[sorted_guas[i][0]]["name"] for i in range(min(2, len(sorted_guas)))]
        top2_elements = [GUA_DIMENSION_MAP[sorted_guas[i][0]]["element"] for i in range(min(2, len(sorted_guas)))]

        # 基础叙事
        if consistent:
            narrative = (
                f"今日{gua_info['name']}卦，{gua_info['meaning']}。"
                f"主导力量为{top2_names[0]}({top2_elements[0]})与{top2_names[1]}({top2_elements[1]})，"
                f"辩证ML引擎判定{direction_text}，置信度{confidence_pct}，与卦义一致。"
            )
        else:
            narrative = (
                f"今日{gua_info['name']}卦，{gua_info['meaning']}。"
                f"主导力量为{top2_names[0]}({top2_elements[0]})与{top2_names[1]}({top2_elements[1]})。"
                f"辩证ML引擎判定{direction_text}，置信度{confidence_pct}。"
                f"注意：ML方向与卦义方向不一致，需警惕矛盾转化的可能。"
            )

        # 增强: 卦象强度 (矛盾激化程度)
        if gua_intensity > 0:
            intensity_level = "低" if gua_intensity < 0.3 else ("中" if gua_intensity < 0.6 else "高")
            narrative += f" 当前矛盾激化程度为{intensity_level}强度(强度指数{gua_intensity:.2f})。"

        # 增强: 变卦提示 (物极必反)
        if changed_gua and changed_gua.get("changed_line_name"):
            line_name = changed_gua["changed_line_name"]
            changed_name = changed_gua.get("name", "未知")
            orig_type = changed_gua.get("original_type", "")
            new_type = changed_gua.get("new_type", "")
            narrative += (
                f" 变卦提示：{line_name}力量最强，若{orig_type}转{new_type}，"
                f"卦象将变为{changed_name}，需警惕物极必反。"
            )

        # 增强: 互卦提示 (内部深层结构)
        if mutual_gua and mutual_gua.get("name"):
            mutual_name = mutual_gua["name"]
            mutual_meaning = mutual_gua.get("meaning", "")
            narrative += f" 深层结构：互卦为{mutual_name}（{mutual_meaning}），揭示内在矛盾演化趋势。"

        return narrative


# ============================================================
# 辩证ML引擎 (Dialectical ML Engine)
# ============================================================

class DialecticalMLEngine:
    """
    辩证ML引擎 — BCRM力学引擎的算法升级

    三层架构 (对应否定之否定):
      L1: 主方向模型 (正题) → LightGBM多分类 (UP/DOWN/FLAT)
      L2: Meta-Labeling (反题) → 对L1信号做"该不该下单"的二次判断
      L3: 辩证裁决 (合题) → 综合L1+L2 + 卦象解释

    理论映射:
      对立统一 → 多分类输出各类概率 = 多空力量对比
      量变质变 → Meta置信度 = 质变发生的确定性
      否定之否定 → L1(正题) → L2(反题) → L3(合题) 的辩证过程
    """

    def __init__(
        self,
        feature_names: List[str],
        feature_names_by_gua: Dict[str, List[str]],
        n_classes: int = 3,  # -1=DOWN, 0=FLAT, 1=UP
    ):
        self.feature_names = feature_names
        self.feature_names_by_gua = feature_names_by_gua
        self.n_classes = n_classes

        # L1: 主方向模型
        self.l1_model = None
        # L2: Meta-Labeling模型 (做多/做空各一个)
        self.l2_model_long = None   # 做多盈利预测
        self.l2_model_short = None  # 做空盈利预测
        # 兼容旧属性名
        self.l2_model = None

        # 卦象映射器
        self.hexagram_mapper = HexagramMapper(feature_names_by_gua)

        # 默认参数 (偏保守，防过拟合)
        self.l1_params = {
            "objective": "multiclass",
            "num_class": 3,
            "max_depth": 5,
            "learning_rate": 0.05,
            "n_estimators": 200,
            "subsample": 0.8,
            "colsample_bytree": 0.7,
            "reg_alpha": 1.0,
            "reg_lambda": 3.0,
            "min_child_weight": 10,
            "random_state": 42,
            "verbose": -1,
        }

        self.l2_params = {
            "objective": "binary",
            "max_depth": 4,
            "learning_rate": 0.03,
            "n_estimators": 150,
            "subsample": 0.8,
            "colsample_bytree": 0.7,
            "reg_alpha": 2.0,
            "reg_lambda": 5.0,
            "min_child_weight": 15,
            "random_state": 42,
            "verbose": -1,
        }

    # --------------------------------------------------------
    # 训练
    # --------------------------------------------------------

    def train_l1(self, X: np.ndarray, y: np.ndarray) -> Dict:
        """
        训练L1主方向模型 (正题)

        y的取值: -1=DOWN, 0=FLAT, 1=UP
        """
        lgb = _get_lgb()

        # 标签映射到0/1/2
        y_mapped = y + 1  # -1→0, 0→1, 1→2

        self.l1_model = lgb.LGBMClassifier(**self.l1_params)
        self.l1_model.fit(X, y_mapped)

        # 卦象映射器用训练集统计量做归一化基准
        self.hexagram_mapper.fit_feature_stats(X, self.feature_names)

        # 训练集表现
        train_pred = self.l1_model.predict(X)
        train_acc = (train_pred == y_mapped).mean()

        # 特征重要性
        importances = self.l1_model.feature_importances_
        top_indices = np.argsort(importances)[::-1][:15]
        top_features = [
            {"name": self.feature_names[i], "importance": float(importances[i])}
            for i in top_indices
        ]

        return {
            "n_samples": len(X),
            "n_features": X.shape[1],
            "train_accuracy": float(train_acc),
            "label_distribution": {
                "down (-1)": int(np.sum(y == -1)),
                "flat (0)": int(np.sum(y == 0)),
                "up (1)": int(np.sum(y == 1)),
            },
            "top_features": top_features,
        }

    def train_l2(self, X: np.ndarray, y: np.ndarray, df: Optional[pd.DataFrame] = None, ref_df: Optional[pd.DataFrame] = None, cycle_phase: Optional[pd.DataFrame] = None) -> Dict:
        """
        训练L2 Meta-Labeling模型 (反题)

        否定之否定: L1给出方向(正题), L2判断"这个方向的收益好不好"(反题)

        V3版本: 标签重定义
          - 不再是简单的"对/错"，而是"相对收益高低"
          - 做多: 收益 > 中位数 → 正样本；收益 < 中位数 → 负样本
          - 做空: 收益 > 中位数 → 正样本；收益 < 中位数 → 负样本
          - 目的: L2学习区分"好交易"和"坏交易"，而不是总是预测"对"

        使用与L1互补的特征体系:
          - 时间维度特征 (周期相位、季节性、时段)
          - 宏观环境特征 (BTC.D趋势、风险偏好)
          - 信号稀有度特征 (近期同类信号频率)
          - 市场结构特征 (趋势成熟度、反转概率)
          - 跨资产验证特征 (Beta、相关性)

        分别训练做多/做空两个二元分类器
        """
        lgb = _get_lgb()

        # 计算L2增强特征 (V2版本)
        from .meta_labeling_features_v2 import MetaLabelingFeaturesV2

        # L1预测 (用于构建L2特征)
        if self.l1_model is not None:
            l1_proba = self._predict_proba(self.l1_model, X)
            l1_pred = np.argmax(l1_proba, axis=1) - 1
        else:
            l1_proba = np.random.rand(len(X), 3)
            l1_proba = l1_proba / l1_proba.sum(axis=1, keepdims=True)
            l1_pred = np.argmax(l1_proba, axis=1) - 1

        ml_features = MetaLabelingFeaturesV2()
        X_l2 = ml_features.compute_base_features(df, l1_pred, l1_proba, ref_df, cycle_phase)

        # 计算每根K线的未来收益 (用于定义L2标签)
        close = df['close'].values
        future_return = np.zeros(len(close))
        for i in range(len(close) - 20):
            future_return[i] = (close[i + 20] - close[i]) / close[i]

        # 做多L2: 当L1预测UP时, 判断这个UP信号的收益是否高于中位数
        long_mask = (l1_pred == 1)
        if long_mask.sum() < 20:
            return {"ok": False, "reason": f"insufficient L1 long signals: {long_mask.sum()}"}

        long_returns = future_return[long_mask]
        long_median = np.median(long_returns)
        y_long = (long_returns > long_median).astype(int)

        X_l2_long = X_l2[long_mask]

        self.l2_model_long = lgb.LGBMClassifier(**self.l2_params)
        self.l2_model_long.fit(X_l2_long, y_long)
        long_pred = self.l2_model_long.predict(X_l2_long)
        long_acc = (long_pred == y_long).mean()

        # 做空L2: 当L1预测DOWN时, 判断这个DOWN信号的收益是否高于中位数
        short_mask = (l1_pred == -1)
        if short_mask.sum() < 20:
            self.l2_model_short = None
            return {
                "ok": True,
                "n_samples": len(X),
                "n_l2_features": X_l2.shape[1],
                "long_train_accuracy": float(long_acc),
                "long_positive_ratio": float(y_long.mean()),
                "long_n_samples": int(long_mask.sum()),
                "long_median_return": float(long_median),
                "short_train_accuracy": None,
                "short_positive_ratio": None,
                "short_n_samples": int(short_mask.sum()),
                "note": "short samples insufficient, only long L2 trained"
            }

        short_returns = -future_return[short_mask]  # 做空收益 = -未来收益
        short_median = np.median(short_returns)
        y_short = (short_returns > short_median).astype(int)

        X_l2_short = X_l2[short_mask]

        self.l2_model_short = lgb.LGBMClassifier(**self.l2_params)
        self.l2_model_short.fit(X_l2_short, y_short)
        short_pred = self.l2_model_short.predict(X_l2_short)
        short_acc = (short_pred == y_short).mean()

        # 兼容旧属性
        self.l2_model = self.l2_model_long
        self._l2_features = X_l2

        return {
            "ok": True,
            "n_samples": len(X),
            "n_l2_features": X_l2.shape[1],
            "long_train_accuracy": float(long_acc),
            "long_positive_ratio": float(y_long.mean()),
            "long_n_samples": int(long_mask.sum()),
            "long_median_return": float(long_median),
            "short_train_accuracy": float(short_acc),
            "short_positive_ratio": float(y_short.mean()),
            "short_n_samples": int(short_mask.sum()),
            "short_median_return": float(short_median),
        }

    # --------------------------------------------------------
    # 预测
    # --------------------------------------------------------

    def predict(self, X: np.ndarray, with_gua: bool = False, df: Optional[pd.DataFrame] = None, ref_df: Optional[pd.DataFrame] = None, cycle_phase: Optional[pd.DataFrame] = None) -> List[Dict]:
        """
        辩证预测 — 三层裁决

        L1(正题): 预测方向 UP/DOWN/FLAT
        L2(反题): 对L1方向做"是否盈利"的二次判断 (使用V2互补特征)
        L3(合题): L1置信度 × L2盈利概率 = 最终置信度

        否定之否定:
          - L1说"做多" → L2说"但这个时机不好、环境不利" → 最终裁决
          - 只有L1和L2都同意, 才执行交易

        Returns:
            每个样本的预测结果字典
        """
        if self.l1_model is None:
            raise ValueError("L1 model not trained")

        results = []
        n = len(X)

        # L1预测 (正题)
        l1_proba = self._predict_proba(self.l1_model, X)  # shape: (n, 3)
        l1_pred = np.argmax(l1_proba, axis=1) - 1  # 映射回 -1/0/1

        # 计算L2增强特征 (V2版本)
        l2_long_proba = None
        l2_short_proba = None
        if (self.l2_model_long is not None) or (self.l2_model_short is not None):
            from .meta_labeling_features_v2 import MetaLabelingFeaturesV2
            ml_features = MetaLabelingFeaturesV2()
            X_l2 = ml_features.compute_base_features(df, l1_pred, l1_proba, ref_df, cycle_phase)

            if self.l2_model_long is not None:
                l2_long_proba = self._predict_binary_proba(self.l2_model_long, X_l2)
            if self.l2_model_short is not None:
                l2_short_proba = self._predict_binary_proba(self.l2_model_short, X_l2)

        for i in range(n):
            direction = int(l1_pred[i])
            l1_confidence = float(np.max(l1_proba[i]))

            # L3: 辩证裁决 (合题)
            # 原始设计: L2仅在L1不确定区(0.4-0.7)介入裁决
            # - L1高自信(>0.7): 直接执行, L2不介入
            # - L1中等自信(0.4-0.7): L2完全裁决
            # - L1低自信(<0.4): 直接拒绝, L2不介入
            if direction == 0:
                final_confidence = l1_confidence * 0.5
                action = "HOLD"
                l2_conf = None
                meta_conf = None
            elif direction == 1:
                # L1做多
                meta_conf = float(l2_long_proba[i]) if l2_long_proba is not None else None
                if l2_long_proba is not None and 0.4 <= l1_confidence <= 0.7:
                    # 不确定区域: L2介入裁决
                    mc = float(l2_long_proba[i])
                    if mc >= 0.5:
                        # L2同意: 保持L1置信度 (不额外增强, 避免过度拟合)
                        final_confidence = l1_confidence
                    else:
                        # L2反对: 降低置信度
                        final_confidence = l1_confidence * mc
                else:
                    # L1高自信或低自信: L2不介入
                    final_confidence = l1_confidence
                l2_conf = meta_conf
                action = "OPEN" if final_confidence > 0.35 else "HOLD"
            else:  # direction == -1
                # L1做空
                meta_conf = float(l2_short_proba[i]) if l2_short_proba is not None else None
                if l2_short_proba is not None and 0.4 <= l1_confidence <= 0.7:
                    mc = float(l2_short_proba[i])
                    if mc >= 0.5:
                        final_confidence = l1_confidence
                    else:
                        final_confidence = l1_confidence * mc
                else:
                    final_confidence = l1_confidence
                l2_conf = meta_conf
                action = "OPEN" if final_confidence > 0.35 else "HOLD"

            result = {
                "direction": direction,  # -1/0/1
                "direction_text": "UP" if direction == 1 else ("DOWN" if direction == -1 else "FLAT"),
                "l1_confidence": round(l1_confidence, 4),
                "l2_confidence": round(l2_conf, 4) if l2_conf is not None else None,
                "meta_confidence": round(meta_conf, 4) if meta_conf is not None else None,
                "final_confidence": round(final_confidence, 4),
                "action": action,
            }

            # 卦象解释 (可选)
            if with_gua:
                gua = self.hexagram_mapper.predict_gua(
                    X[i], self.feature_names, direction, final_confidence
                )
                result["hexagram"] = gua

            results.append(result)

        return results

    def _predict_proba(self, model, X) -> np.ndarray:
        """兼容 LGBMClassifier 和 Booster 的 predict_proba (多分类)"""
        if hasattr(model, 'predict_proba'):
            return model.predict_proba(X)
        else:
            # Booster.predict 对多分类直接返回概率矩阵 (n, n_classes)
            return model.predict(X)

    def _predict_binary_proba(self, model, X) -> np.ndarray:
        """兼容 LGBMClassifier 和 Booster 的 predict_proba (二分类, 返回 class 1 的概率)"""
        if hasattr(model, 'predict_proba'):
            return model.predict_proba(X)[:, 1]
        else:
            # Booster 二分类 predict 直接返回 class 1 的概率 (1D array)
            return model.predict(X)

    def predict_single(self, X_row: np.ndarray, with_gua: bool = False) -> Dict:
        """单样本预测"""
        return self.predict(X_row.reshape(1, -1), with_gua=with_gua)[0]

    # --------------------------------------------------------
    # 模型保存/加载
    # --------------------------------------------------------

    def save(self, dir_path: str) -> bool:
        """保存模型"""
        os.makedirs(dir_path, exist_ok=True)
        try:
            if self.l1_model:
                self.l1_model.booster_.save_model(os.path.join(dir_path, "l1_model.txt"))
            if self.l2_model:
                self.l2_model.booster_.save_model(os.path.join(dir_path, "l2_model.txt"))

            meta = {
                "feature_names": self.feature_names,
                "feature_names_by_gua": self.feature_names_by_gua,
                "n_classes": self.n_classes,
            }
            with open(os.path.join(dir_path, "model_meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def load(self, dir_path: str) -> bool:
        """加载模型"""
        lgb = _get_lgb()
        try:
            meta_path = os.path.join(dir_path, "model_meta.json")
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self.feature_names = meta["feature_names"]
            self.feature_names_by_gua = meta["feature_names_by_gua"]
            self.n_classes = meta.get("n_classes", 3)
            self.hexagram_mapper = HexagramMapper(self.feature_names_by_gua)

            l1_path = os.path.join(dir_path, "l1_model.txt")
            if os.path.exists(l1_path):
                self.l1_model = lgb.Booster(model_file=l1_path)

            l2_path = os.path.join(dir_path, "l2_model.txt")
            if os.path.exists(l2_path):
                self.l2_model = lgb.Booster(model_file=l2_path)

            return True
        except Exception:
            return False
