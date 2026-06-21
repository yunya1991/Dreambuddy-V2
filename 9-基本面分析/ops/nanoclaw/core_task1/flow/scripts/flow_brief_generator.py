#!/usr/bin/env python3
"""
资金流分析简报生成器 - Flow Brief Generator

功能:
1. 加载最新 Regime 记录和信号数据
2. 生成资金流三层状态机分析简报
3. 输出 Markdown 格式简报，包含关键指标、信号摘要、操作建议
4. 支持与新闻分析信号融合（如有）

简报格式参考新闻分析 skill 的 brief_v3 优化版
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


# =============================================================================
# 配置
# =============================================================================

FLOW_DIR = Path(__file__).resolve().parents[1]
HISTORY_DIR = FLOW_DIR / "historical_data"
OUTPUTS_DIR = FLOW_DIR / "outputs"
SCRIPTS_DIR = FLOW_DIR / "scripts"

# 确保目录存在
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class FlowSignal:
    """资金流信号数据"""
    timestamp: str
    composite: float
    bias: str  # bullish/bearish/neutral
    confidence: float
    filter_status: str  # enable/disable

    # 三层信号
    exogenous_signal: float
    leverage_signal: float
    onchain_signal: float

    # 诊断信息
    data_freshness: Dict[str, str]

    # 衍生指标
    regime_strength: str  # strong/moderate/weak
    signal_change: str  # strengthening/weakening/stable


class FlowBriefGenerator:
    """资金流简报生成器"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or FLOW_DIR
        self.history_dir = HISTORY_DIR
        self.outputs_dir = OUTPUTS_DIR

    def load_latest_regime(self) -> Optional[Dict]:
        """加载最新 Regime 记录"""
        outputs_regime = sorted(self.outputs_dir.glob("flow_regime_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        for file_path in outputs_regime:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                continue
        return None

    def load_regime_history(self, limit: int = 20) -> List[Dict]:
        """加载最近 N 条 Regime 记录"""
        records: List[Dict] = []
        files = sorted(self.outputs_dir.glob("flow_regime_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        for file_path in files[: max(1, int(limit))]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    records.append(json.load(f))
            except Exception:
                continue
        return records

    def load_latest_btc_price(self) -> Optional[float]:
        try:
            import urllib.request
            req = urllib.request.Request("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(obj, dict):
                v = obj.get("price")
                return float(v)
        except Exception:
            try:
                import urllib.request
                req = urllib.request.Request("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    obj = json.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(obj, dict):
                    btc = obj.get("bitcoin")
                    if isinstance(btc, dict):
                        v = btc.get("usd")
                        return float(v)
            except Exception:
                return self.load_latest_btc_price_local()
        return None

    def load_latest_btc_price_local(self) -> Optional[float]:
        try:
            here = Path(__file__).resolve()
        except Exception:
            return None
        repo_root = None
        for p in here.parents:
            try:
                if (p / "user_data" / "data").exists():
                    repo_root = p
                    break
            except Exception:
                continue
        if repo_root is None:
            return None
        data_root = repo_root / "user_data" / "data"
        candidates: List[Path] = []
        for sub in ("gateio", "gate"):
            d = data_root / sub
            if d.exists():
                for nm in (
                    "BTC_USDT_USDT-5m-futures.json",
                    "BTC_USDT-5m.json",
                    "BTC_USDT_USDT-1h-futures.json",
                    "BTC_USDT-1h.json",
                    "BTC_USDT_USDT-1d-futures.json",
                    "BTC_USDT-1d.json",
                ):
                    q = d / nm
                    if q.exists() and q.is_file():
                        candidates.append(q)
        if not candidates:
            try:
                for pat in ("**/*BTC*USDT*-5m*.json", "**/*BTC*USDT*-1h*.json", "**/*BTC*USDT*-1d*.json"):
                    for q in data_root.glob(pat):
                        if q.is_file():
                            candidates.append(q)
                candidates = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)[:10]
            except Exception:
                candidates = []
        if not candidates:
            return None
        candidates = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)
        for q in candidates:
            try:
                obj = json.loads(q.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            rows = None
            if isinstance(obj, list):
                rows = obj
            elif isinstance(obj, dict):
                rows = obj.get("data") if isinstance(obj.get("data"), list) else None
            if not isinstance(rows, list) or not rows:
                continue
            last = rows[-1]
            if isinstance(last, (list, tuple)) and len(last) >= 5:
                try:
                    px = float(last[4])
                except Exception:
                    px = None
                if px is not None and px > 0:
                    return float(px)
        return None

    def try_load_news_signal(self) -> Optional[Dict]:
        """尝试加载新闻分析信号（用于融合）"""
        outputs_dir = Path("/workspace/ops/nanoclaw/core_task1/outputs")

        # 查找最新的新闻分析结果
        news_files = sorted(outputs_dir.glob("event_ledger_*.jsonl"), reverse=True)

        for file_path in news_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        latest = json.loads(lines[-1])
                        return {
                            'sentiment': latest.get('weighted_sentiment', 0),
                            'event_count': latest.get('event_count', 0),
                            'timestamp': latest.get('timestamp', '')
                        }
            except Exception:
                continue

        return None

    def calculate_signal_trend(self, history: List[Dict]) -> str:
        """计算信号趋势"""
        if len(history) < 2:
            return "stable"

        recent_composite = history[0].get('composite', 0) if history else 0
        prev_composite = history[1].get('composite', 0) if len(history) > 1 else 0

        diff = recent_composite - prev_composite
        if abs(diff) < 0.05:
            return "stable"
        elif diff > 0:
            return "strengthening"
        else:
            return "weakening"

    def determine_regime_strength(self, confidence: float, composite: float) -> str:
        """判断 Regime 强度"""
        if confidence >= 0.8 and abs(composite) >= 0.5:
            return "strong"
        elif confidence >= 0.6 and abs(composite) >= 0.3:
            return "moderate"
        else:
            return "weak"

    def parse_flow_signal(self, record: Dict) -> FlowSignal:
        """解析 Regime 记录为 FlowSignal"""
        layer_signals = record.get('layer_signals', {})
        diagnostics = record.get('diagnostics', {})
        regime_out = record.get('regime_output', {}) or {}

        composite = record.get('composite', 0)
        confidence = record.get('confidence', 0.5)

        return FlowSignal(
            timestamp=record.get('timestamp', ''),
            composite=composite,
            bias=regime_out.get('bias', record.get('bias', 'neutral')),
            confidence=confidence,
            filter_status=regime_out.get('filter', record.get('filter', 'enable')),
            exogenous_signal=layer_signals.get('exogenous', 0),
            leverage_signal=layer_signals.get('leverage', 0),
            onchain_signal=layer_signals.get('onchain', 0),
            data_freshness=diagnostics.get('data_freshness', {}),
            regime_strength=self.determine_regime_strength(confidence, composite),
            signal_change="stable"  # 后续通过历史数据更新
        )

    def calculate_position_recommendation(self, signal: FlowSignal) -> Dict:
        """计算仓位建议"""
        bias = signal.bias
        confidence = signal.confidence
        filter_status = signal.filter_status

        # 默认配置
        base_position = 0.5  # 基础仓位 50%
        target_position = 0.8  # 目标仓位 80%
        min_position = 0.1   # 最小仓位 10%

        action = "HOLD"
        position_change = "→"
        reasoning = []

        if filter_status == "disable":
            action = "HOLD"
            position = base_position
            reasoning.append("信号滤波器禁用，维持基础仓位")
        elif bias == "bullish":
            if confidence >= 0.7:
                action = "INCREASE"
                position = target_position
                position_change = "↑"
                reasoning.append("强烈看多信号，建议加仓")
            elif confidence >= 0.5:
                action = "HOLD"
                position = base_position + 0.1
                position_change = "→"
                reasoning.append("温和看多信号，维持偏高仓位")
            else:
                action = "HOLD"
                position = base_position
                reasoning.append("看多信号较弱，维持基础仓位")
        elif bias == "bearish":
            if confidence >= 0.7:
                action = "REDUCE"
                position = min_position
                position_change = "↓"
                reasoning.append("强烈看空信号，建议减仓")
            elif confidence >= 0.5:
                action = "REDUCE"
                position = base_position - 0.2
                position_change = "↓"
                reasoning.append("温和看空信号，建议适度减仓")
            else:
                action = "HOLD"
                position = base_position
                reasoning.append("看空信号较弱，维持基础仓位")
        else:  # neutral
            action = "HOLD"
            position = base_position
            reasoning.append("中性信号，维持基础仓位")

        return {
            'action': action,
            'position': position,
            'position_change': position_change,
            'reasoning': reasoning
        }

    def generate_fused_signal(self, flow_signal: FlowSignal, news_data: Dict = None) -> Dict:
        """计算融合信号（资金流 + 新闻分析）"""
        flow_weight = 0.6
        news_weight = 0.4

        # 资金流信号标准化 (-1 到 1)
        flow_normalized = flow_signal.composite
        if flow_signal.bias == "bearish":
            flow_normalized = -abs(flow_signal.composite)
        elif flow_signal.bias == "bullish":
            flow_normalized = abs(flow_signal.composite)

        # 新闻信号
        news_normalized = 0
        if news_data:
            news_normalized = news_data.get('sentiment', 0) * 2 - 1  # 标准化到 -1~1

        # 融合
        fused = flow_weight * flow_normalized + news_weight * news_normalized

        # 融合后判断
        if fused > 0.15:
            fused_bias = "bullish"
        elif fused < -0.15:
            fused_bias = "bearish"
        else:
            fused_bias = "neutral"

        fused_confidence = (flow_signal.confidence * flow_weight +
                          (news_data.get('confidence', 0.5) if news_data else 0.5) * news_weight)

        return {
            'fused_signal': round(fused, 4),
            'fused_bias': fused_bias,
            'fused_confidence': round(fused_confidence, 4),
            'flow_weight': flow_weight,
            'news_weight': news_weight
        }

    def generate_brief(self, news_data: Dict = None) -> str:
        """生成资金流简报"""
        # 加载数据
        latest_regime = self.load_latest_regime()
        regime_history = self.load_regime_history(limit=10)
        latest_price = self.load_latest_btc_price()

        if not latest_regime:
            return self._generate_no_data_brief()

        # 解析信号
        signal = self.parse_flow_signal(latest_regime)
        signal.signal_change = self.calculate_signal_trend(regime_history)

        # 计算仓位建议
        position_rec = self.calculate_position_recommendation(signal)

        # 融合信号
        fused = self.generate_fused_signal(signal, news_data)

        # 生成 Markdown
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")

        # 信号趋势图标
        trend_icon = {"strengthening": "📈", "weakening": "📉", "stable": "➡️"}
        bias_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}

        md = f"""# 资金流三层状态机简报

**生成时间**: {now}
**分析框架**: 资金流三层状态机 (Exogenous → Leverage → Onchain → Regime)
**信号状态**: {bias_icon.get(signal.bias, '➖')} {signal.bias.upper()} | 置信度：{signal.confidence:.2f}

---

## 📊 核心信号概览

| 指标 | 数值 | 阈值 | 状态 |
|------|------|------|------|
| **Regime Bias** | {signal.bias.upper()} | ±0.15 | {bias_icon.get(signal.bias, '➖')} |
| **Composite 信号** | {signal.composite:+.4f} | ±0.15 | {"有效" if abs(signal.composite) >= 0.15 else "无效"} |
| **置信度** | {signal.confidence:.2f} | ≥0.5 | {"高" if signal.confidence >= 0.7 else "中" if signal.confidence >= 0.5 else "低"} |
| **信号趋势** | {signal.signal_change} | - | {trend_icon.get(signal.signal_change, '➡️')} |
| **滤波器状态** | {signal.filter_status} | - | {"启用" if signal.filter_status == 'enable' else "禁用"} |

---

## 📈 三层信号分解

| 层级 | 信号值 | 权重 | 贡献 | 状态 |
|------|--------|------|------|------|
| **Exogenous Flow** | {signal.exogenous_signal:+.4f} | 40% | {signal.exogenous_signal * 0.4:+.4f} | {"利好" if signal.exogenous_signal > 0.1 else "利空" if signal.exogenous_signal < -0.1 else "中性"} |
| **Leverage** | {signal.leverage_signal:+.4f} | 30% | {signal.leverage_signal * 0.3:+.4f} | {"利好" if signal.leverage_signal > 0.1 else "利空" if signal.leverage_signal < -0.1 else "中性"} |
| **Onchain** | {signal.onchain_signal:+.4f} | 30% | {signal.onchain_signal * 0.3:+.4f} | {"利好" if signal.onchain_signal > 0.1 else "利空" if signal.onchain_signal < -0.1 else "中性"} |
| **Composite** | {signal.composite:+.4f} | 100% | - | {bias_icon.get(signal.bias, '➖')} |

---

## 💼 动态仓位建议

### 今日仓位配置

```
┌─────────────────────────────────────────────────────────┐
│  建议动作：{position_rec['action']:<20}                            │
│  建议仓位：{position_rec['position']*100:.0f}% {position_rec['position_change']}                      │
│  信号阈值：±0.15（Regime 门槛）                     │
│  风险约束：readonly_advisory（仅供参考）          │
└─────────────────────────────────────────────────────────┘
```

### 仓位逻辑
"""

        for reason in position_rec['reasoning']:
            md += f"- {reason}\n"

        # 融合信号（如有新闻数据）
        if news_data:
            flow_normalized = signal.composite
            if signal.bias == "bearish":
                flow_normalized = -abs(signal.composite)
            elif signal.bias == "bullish":
                flow_normalized = abs(signal.composite)
            news_normalized = (news_data.get('sentiment', 0) * 2 - 1)
            md += f"""
---

## 🔗 信号融合（资金流 + 新闻分析）

### 融合计算
```
fused_signal = {fused['flow_weight']:.1f} × flow_signal + {fused['news_weight']:.1f} × news_signal
             = {fused['flow_weight']:.1f} × {flow_normalized:.4f} + {fused['news_weight']:.1f} × {news_normalized:.4f}
             = {fused['fused_signal']:+.4f}
```

### 融合结果
| 信号源 | 信号值 | Bias | 置信度 |
|--------|--------|------|--------|
| 资金流 | {flow_normalized:+.4f} | {signal.bias} | {signal.confidence:.2f} |
| 新闻分析 | {news_normalized:+.4f} | {news_data.get('bias', 'neutral')} | {news_data.get('confidence', 0.5):.2f} |
| **融合** | {fused['fused_signal']:+.4f} | {fused['fused_bias']} | {fused['fused_confidence']:.2f} |
"""

        # 历史信号趋势
        md += """
---

## 📉 信号趋势（最近 10 条）

| 时间 | Bias | Composite | 置信度 | 趋势 |
|------|------|-----------|--------|------|
"""

        for i, record in enumerate(regime_history[:10]):
            ts = record.get('timestamp', '')[:16] if record.get('timestamp') else 'N/A'
            ro = record.get('regime_output', {}) or {}
            bias = ro.get('bias', record.get('bias', 'neutral'))
            composite = record.get('composite', 0)
            confidence = record.get('confidence', 0)

            # 计算与前一条的趋势
            if i < len(regime_history) - 1:
                prev = regime_history[i + 1].get('composite', 0) if i + 1 < len(regime_history) else 0
                if composite > prev + 0.05:
                    trend = "📈"
                elif composite < prev - 0.05:
                    trend = "📉"
                else:
                    trend = "➡️"
            else:
                trend = "➡️"

            md += f"| {ts} | {bias_icon.get(bias, '➖')} {bias} | {composite:+.4f} | {confidence:.2f} | {trend} |\n"

        # 数据新鲜度诊断
        md += """
---

## 🔍 数据新鲜度诊断

"""

        if signal.data_freshness:
            now_dt = datetime.now(timezone.utc)
            for layer, ts_str in signal.data_freshness.items():
                try:
                    layer_dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    age_minutes = (now_dt - layer_dt).total_seconds() / 60
                    status = "✅" if age_minutes < 60 else "⚠️" if age_minutes < 120 else "❌"
                    md += f"- **{layer.capitalize()}**: {ts_str} ({age_minutes:.0f} 分钟前) {status}\n"
                except Exception:
                    md += f"- **{layer.capitalize()}**: {ts_str} (解析失败)\n"
        else:
            md += "- 数据新鲜度信息暂不可用\n"

        # 价格信息
        if latest_price:
            md += f"""
---

## 💰 价格参考

| 指标 | 数值 |
|------|------|
| **BTC 最新价** | ${latest_price:,.2f} |
"""

        # 策略建议
        md += f"""
---

## 📋 策略总结

### 市场状态判定
1. **Regime 状态**: {bias_icon.get(signal.bias, '➖')} {signal.bias.upper()} (Composite: {signal.composite:+.4f})
2. **信号强度**: {signal.regime_strength} (置信度: {signal.confidence:.2f})
3. **信号趋势**: {trend_icon.get(signal.signal_change, '➡️')} {signal.signal_change}

### 操作建议
1. **仓位配置**: {position_rec['position']*100:.0f}% ({position_rec['action']})
2. **执行方式**: 分步执行，避免一次性建仓/平仓
3. **风控要点**:
   - 止损位：5%
   - 止盈位：10%
   - 最大回撤容忍：20%

### 观察要点
"""

        # 根据 Bias 给出观察要点
        if signal.bias == "bullish":
            md += """- 关注资金流向持续性
- 监控杠杆率变化
- 等待新闻面确认
"""
        elif signal.bias == "bearish":
            md += """- 关注下行压力来源
- 监控清算风险
- 警惕超跌反弹
"""
        else:
            md += """- 等待更明确的方向信号
- 关注宏观事件催化
- 维持区间操作思路
"""

        # 脚注
        md += f"""
---

## ⚠️ 风险提示

- 本简报基于三层状态机模型生成，仅供参考
- 加密市场波动剧烈，请谨慎决策
- 历史表现不代表未来收益
- 建议结合多维度信息综合判断

---

**简报版本**: Flow Brief v1.0
**数据源**: {self.data_dir.as_posix()}/
**下一份更新**: 按定时触发配置执行

*本简报由 flow_brief_generator.py 生成 | 不构成投资建议*
"""

        return md

    def _generate_no_data_brief(self) -> str:
        """生成无数据时的简报"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")

        return f"""# 资金流三层状态机简报

**生成时间**: {now}
**状态**: ⚠️ 数据暂不可用

---

## 📊 数据状态

当前系统暂未积累足够的 Regime 历史记录，无法生成完整简报。

### 可能原因
1. 系统刚部署，尚未开始数据采集
2. 数据目录路径变更
3. Regime 计算模块尚未执行

### 解决建议
1. 运行 Regime 计算模块，生成初始数据
2. 等待下一个数据采集周期
3. 检查数据目录配置

---

## 📋 临时参考

在数据积累期间，建议参考：
- 新闻分析 skill 的每日简报
- 传统技术指标分析
- 链上数据监控

---

**简报版本**: Flow Brief v1.0
**状态**: 数据不足

*本简报由 flow_brief_generator.py 生成 | 不构成投资建议*
"""

    def save_brief(self, md_content: str, output_path: Optional[Path] = None) -> Path:
        """保存简报到文件"""
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = self.outputs_dir / f"flow_brief_{ts}.md"

        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        return output_path


# =============================================================================
# 命令行入口
# =============================================================================

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='生成资金流分析简报')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件路径')
    parser.add_argument('--with-news', action='store_true', help='尝试加载新闻分析数据进行融合')
    args = parser.parse_args()

    print("=" * 60)
    print("资金流简报生成器")
    print("=" * 60)

    generator = FlowBriefGenerator()

    # 尝试加载新闻数据
    news_data = None
    if args.with_news:
        print("\n[1/3] 加载新闻分析数据...")
        news_data = generator.try_load_news_signal()
        if news_data:
            print(f"  已加载新闻信号：sentiment={news_data.get('sentiment', 0):.4f}")
        else:
            print("  未找到新闻分析数据，仅使用资金流信号")

    # 生成简报
    print("\n[2/3] 生成资金流简报...")
    md_content = generator.generate_brief(news_data)

    # 保存
    print("\n[3/3] 保存简报...")
    output_path = Path(args.output) if args.output else None
    saved_path = generator.save_brief(md_content, output_path)
    print(f"  简报已保存：{saved_path}")

    # 输出摘要
    latest_regime = generator.load_latest_regime()
    if latest_regime:
        ro = latest_regime.get("regime_output", {}) or {}
        print("\n" + "=" * 60)
        print("信号摘要:")
        print(f"  Bias: {str(ro.get('bias', latest_regime.get('bias', 'neutral'))).upper()}")
        print(f"  Composite: {latest_regime.get('composite', 0):+.4f}")
        print(f"  Confidence: {latest_regime.get('confidence', 0):.2f}")
        print(f"  Filter: {str(ro.get('filter', latest_regime.get('filter', 'enable')))}")
        print("=" * 60)

    return saved_path


if __name__ == "__main__":
    main()
