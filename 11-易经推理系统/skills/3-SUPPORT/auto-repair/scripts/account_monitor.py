#!/usr/bin/env python3
"""
账户隔离监控系统 v1.0
自动扫描日志和配置，确保系统不混淆实盘和模拟盘
"""

import os
import re
import json
import yaml
import toml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ==================== 配置区 ====================
WORKSPACE = Path.home() / "WorkBuddy" / "20260415144304"
CONFIG_FILE = WORKSPACE / ".workbuddy" / "account_monitor_config.yaml"
LEDGER_FILE = WORKSPACE / ".workbuddy" / "memory" / "a6_ledger.md"
OKX_CONFIG = Path.home() / ".okx" / "config.toml"
REPORTS_DIR = WORKSPACE / "reports"

# 扫描范围配置
SCAN_DIRS = [
    WORKSPACE / "reports",
    WORKSPACE / ".workbuddy" / "memory",
    WORKSPACE / ".workbuddy" / "skills",
]

# 关键词配置
ACCOUNT_KEYWORDS = {
    "live": ["实盘", "live", "main", "a5", "实盘账户", "实盘持仓"],
    "demo": ["demo", "模拟盘", "dreamdemo", "模拟账户", "模拟持仓", "测试"],
}

# 危险操作关键词
DANGEROUS_KEYWORDS = [
    "swap place",
    "swap close",
    "批量平仓",
    "市价平多",
    "市价平空",
    "止损",
    "止盈",
]

# ==================== 核心类 ====================

class AccountMonitor:
    """账户隔离监控器"""
    
    def __init__(self):
        self.config = self._load_config()
        self.issues = []
        self.warnings = []
        self.stats = {
            "live_mentions": 0,
            "demo_mentions": 0,
            "confusion_risks": 0,
            "last_scan": None,
        }
    
    def _load_config(self) -> Dict:
        """加载监控配置"""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        
        # 默认配置
        default_config = {
            "monitored_accounts": {
                "live": {
                    "profile": "A5",
                    "status": "disabled",  # 当前禁用
                    "note": "A5实盘，2026-04-24暂停监控"
                },
                "demo": {
                    "profile": "dreamdemo",
                    "status": "active",
                    "note": "当前唯一监控账户"
                }
            },
            "scan_settings": {
                "check_dangling_live": True,    # 检查悬空的live引用
                "check_account_confusion": True,  # 检查账户混淆
                "check_pending_tasks": True,      # 检查待执行任务
            },
            "auto_actions": {
                "flag_confusion": True,     # 标记混淆风险
                "quarantine_suspicious": False,  # 隔离可疑操作
            }
        }
        
        # 保存默认配置
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)
        
        return default_config
    
    def save_config(self, config: Dict):
        """保存配置"""
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    def scan_reports(self) -> Dict[str, List[str]]:
        """扫描报告目录，检测账户引用"""
        findings = {"live": [], "demo": [], "confusion": []}
        
        if not REPORTS_DIR.exists():
            return findings
        
        # 获取最近7天的报告
        cutoff = datetime.now() - timedelta(days=7)
        
        for report_file in REPORTS_DIR.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                if mtime < cutoff:
                    continue
                
                with open(report_file, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # 提取文件名中的日期
                file_date = report_file.stem
                
                # 检测关键词
                live_score = 0
                demo_score = 0
                live_contexts = []
                demo_contexts = []
                
                for keyword in ACCOUNT_KEYWORDS["live"]:
                    if keyword.lower() in content.lower():
                        live_score += 1
                        live_contexts.append(f"[{keyword}] in {file_date}")
                
                for keyword in ACCOUNT_KEYWORDS["demo"]:
                    if keyword.lower() in content.lower():
                        demo_score += 1
                        demo_contexts.append(f"[{keyword}] in {file_date}")
                
                # 检测混淆风险：同一文件中同时出现live和demo
                # 但需要更精确的上下文判断
                if live_score > 0 and demo_score > 0:
                    # 计算净风险分数（排除正常的项目代号提及）
                    # 如果demo_score远大于live_score，说明主要是模拟盘记录
                    # 如果两者相近，需要进一步检查
                    if abs(live_score - demo_score) <= 1 and live_score >= 2:
                        findings["confusion"].append({
                            "file": file_date,
                            "live_score": live_score,
                            "demo_score": demo_score,
                            "risk": "⚠️ 需人工确认：实盘模拟盘提及相当"
                        })
                        self.stats["confusion_risks"] += 1
                    # 如果live_score很高且demo_score很低，可能是真实风险
                    elif live_score > demo_score * 2 and live_score >= 3:
                        findings["confusion"].append({
                            "file": file_date,
                            "live_score": live_score,
                            "demo_score": demo_score,
                            "risk": "🔴 高风险：实盘提及明显多于模拟盘"
                        })
                        self.stats["confusion_risks"] += 1
                    # 否则标记为正常（历史过渡期记录）
                    else:
                        # 正常：当前切换期，两者在报告中并存是合理的
                        pass
                
                if live_score > 0:
                    findings["live"].extend(live_contexts[:3])  # 限制数量
                    self.stats["live_mentions"] += live_score
                
                if demo_score > 0:
                    findings["demo"].extend(demo_contexts[:3])
                    self.stats["demo_mentions"] += demo_score
                    
            except Exception as e:
                self.warnings.append(f"扫描 {report_file.name} 失败: {e}")
        
        return findings
    
    def scan_config_files(self) -> Dict:
        """扫描配置文件，验证账户状态"""
        config_status = {
            "okx_config": {"exists": False, "profiles": []},
            "skill_configs": [],
            "issues": []
        }
        
        # 检查OKX配置
        if OKX_CONFIG.exists():
            config_status["okx_config"]["exists"] = True
            try:
                with open(OKX_CONFIG, "r") as f:
                    content = f.read()
                    toml_content = toml.loads(content)
                    
                    if "profiles" in toml_content:
                        for name, profile in toml_content["profiles"].items():
                            is_disabled = "[disabled]" in str(profile) or profile.get("disabled", False)
                            is_demo = profile.get("demo", False)
                            
                            profile_info = {
                                "name": name,
                                "is_demo": is_demo,
                                "is_disabled": is_disabled,
                                "status": "disabled" if is_disabled else ("demo" if is_demo else "live")
                            }
                            
                            # 检查关键字段
                            if "api_key" not in profile:
                                config_status["issues"].append({
                                    "severity": "warning",
                                    "profile": name,
                                    "issue": f"Profile {name} 缺少 api_key"
                                })
                            
                            config_status["okx_config"]["profiles"].append(profile_info)
                            
            except Exception as e:
                config_status["issues"].append({
                    "severity": "error",
                    "file": str(OKX_CONFIG),
                    "issue": f"OKX配置解析失败: {e}"
                })
        
        # 检查Skill配置中的账户引用
        skills_dir = WORKSPACE / ".workbuddy" / "skills"
        if skills_dir.exists():
            for skill_file in skills_dir.rglob("SKILL.md"):
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    skill_name = skill_file.parent.name
                    live_refs = []
                    demo_refs = []
                    
                    for kw in ACCOUNT_KEYWORDS["live"]:
                        if kw.lower() in content.lower():
                            live_refs.append(kw)
                    
                    for kw in ACCOUNT_KEYWORDS["demo"]:
                        if kw.lower() in content.lower():
                            demo_refs.append(kw)
                    
                    if live_refs or demo_refs:
                        config_status["skill_configs"].append({
                            "skill": skill_name,
                            "file": str(skill_file.relative_to(WORKSPACE)),
                            "live_keywords": live_refs,
                            "demo_keywords": demo_refs,
                            "has_confusion": bool(live_refs and demo_refs)
                        })
                        
                        if live_refs and demo_refs:
                            config_status["issues"].append({
                                "severity": "warning",
                                "skill": skill_name,
                                "issue": f"Skill {skill_name} 同时引用了实盘和模拟盘关键词"
                            })
                            
                except Exception as e:
                    self.warnings.append(f"扫描 Skill配置 {skill_file.name} 失败: {e}")
        
        return config_status
    
    def scan_memory_files(self) -> Dict:
        """扫描记忆文件"""
        memory_dir = WORKSPACE / ".workbuddy" / "memory"
        memory_status = {
            "account_context": [],
            "pending_actions": [],
            "conflicts": []
        }
        
        if not memory_dir.exists():
            return memory_status
        
        # 扫描记忆文件
        for mem_file in memory_dir.glob("*.md"):
            try:
                with open(mem_file, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # 检测当前监控状态
                if "当前监控" in content or "monitored_accounts" in content:
                    # 提取账户状态信息
                    live_active = "A5" in content and "暂停" not in content and "冻结" not in content
                    demo_active = "dreamdemo" in content and ("active" in content.lower() or "唯一" in content)
                    
                    if live_active and demo_active:
                        memory_status["conflicts"].append({
                            "file": mem_file.name,
                            "issue": "记忆文件中声明了冲突的账户监控状态"
                        })
                
                # 检测待执行操作
                if any(kw in content for kw in ["待执行", "pending", "TODO", "待处理"]):
                    memory_status["pending_actions"].append(mem_file.name)
                    
            except Exception as e:
                self.warnings.append(f"扫描记忆文件 {mem_file.name} 失败: {e}")
        
        return memory_status
    
    def check_current_account_policy(self) -> Dict:
        """检查当前账户策略是否一致"""
        policy = {
            "primary_account": None,
            "secondary_accounts": [],
            "is_consistent": True,
            "recommendations": []
        }
        
        # 读取配置中的监控账户
        monitored = self.config.get("monitored_accounts", {})
        
        active_accounts = []
        disabled_accounts = []
        
        for name, info in monitored.items():
            if info.get("status") == "active":
                active_accounts.append(name)
            else:
                disabled_accounts.append(name)
        
        # 验证策略一致性
        if len(active_accounts) == 0:
            policy["recommendations"].append("⚠️ 没有活跃的监控账户!")
            policy["is_consistent"] = False
        elif len(active_accounts) > 1:
            policy["recommendations"].append(f"⚠️ 有{len(active_accounts)}个活跃账户: {active_accounts}，建议统一为单一账户")
            policy["is_consistent"] = False
        else:
            policy["primary_account"] = active_accounts[0]
            policy["recommendations"].append(f"✅ 单一活跃账户: {active_accounts[0]}")
        
        policy["secondary_accounts"] = disabled_accounts
        
        return policy
    
    def generate_report(self) -> str:
        """生成完整的账户监控报告"""
        self.stats["last_scan"] = datetime.now().isoformat()
        
        report_lines = [
            "# 🔒 账户隔离监控报告",
            f"**扫描时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "---",
            "",
            "## 📊 统计概览",
            f"- 实盘提及次数: {self.stats['live_mentions']}",
            f"- 模拟盘提及次数: {self.stats['demo_mentions']}",
            f"- 账户混淆风险: {self.stats['confusion_risks']}",
            f"- 警告数量: {len(self.warnings)}",
            "",
        ]
        
        # 账户策略检查
        policy = self.check_current_account_policy()
        report_lines.extend([
            "## 🎯 当前账户策略",
            f"- 主监控账户: **{policy['primary_account'] or '未设置'}**",
            f"- 已禁用账户: {', '.join(policy['secondary_accounts']) or '无'}",
            f"- 策略一致性: {'✅ 一致' if policy['is_consistent'] else '⚠️ 不一致'}",
            "",
        ])
        
        if policy['recommendations']:
            report_lines.append("### 策略建议")
            for rec in policy['recommendations']:
                report_lines.append(f"- {rec}")
            report_lines.append("")
        
        # 配置扫描结果
        config_status = self.scan_config_files()
        report_lines.extend([
            "## ⚙️ 配置文件状态",
            f"- OKX配置存在: {'✅' if config_status['okx_config']['exists'] else '❌'}",
            "",
        ])
        
        if config_status['okx_config']['profiles']:
            report_lines.append("### Profile列表")
            for profile in config_status['okx_config']['profiles']:
                status_icon = "🟢" if profile['status'] == 'live' else "🔵" if profile['is_demo'] else "🔴"
                disabled_icon = " [已禁用]" if profile['is_disabled'] else ""
                report_lines.append(f"- {status_icon} {profile['name']}: {profile['status']}{disabled_icon}")
            report_lines.append("")
        
        # 问题汇总
        if config_status['issues']:
            report_lines.append("### ⚠️ 配置文件问题")
            for issue in config_status['issues']:
                severity_icon = "🔴" if issue['severity'] == 'error' else "🟡"
                if 'skill' in issue:
                    report_lines.append(f"{severity_icon} [{issue['skill']}] {issue['issue']}")
                elif 'profile' in issue:
                    report_lines.append(f"{severity_icon} [{issue['profile']}] {issue['issue']}")
                else:
                    report_lines.append(f"{severity_icon} {issue['issue']}")
            report_lines.append("")
        
        # 记忆文件检查
        memory_status = self.scan_memory_files()
        if memory_status['conflicts']:
            report_lines.extend([
                "### ⚠️ 记忆文件冲突",
            ])
            for conflict in memory_status['conflicts']:
                report_lines.append(f"- [{conflict['file']}] {conflict['issue']}")
            report_lines.append("")
        
        # 账户混淆检测
        findings = self.scan_reports()
        if findings['confusion']:
            report_lines.extend([
                "### 🔴 账户混淆风险",
                "| 文件 | 实盘分 | 模拟分 | 风险 |",
                "|------|--------|--------|------|",
            ])
            for item in findings['confusion']:
                report_lines.append(f"| {item['file']} | {item['live_score']} | {item['demo_score']} | {item['risk']} |")
            report_lines.append("")
        
        # 风险评估
        report_lines.extend([
            "## 🛡️ 风险评估",
        ])
        
        risk_level = "低"
        risk_reasons = []
        
        if self.stats['confusion_risks'] > 0:
            risk_level = "高"
            risk_reasons.append(f"检测到{self.stats['confusion_risks']}个账户混淆风险")
        
        if not policy['is_consistent']:
            risk_level = "中" if risk_level == "低" else risk_level
            risk_reasons.append("账户策略不一致")
        
        if config_status['issues']:
            risk_level = "中" if risk_level == "低" else risk_level
            risk_reasons.append(f"配置文件存在{len(config_status['issues'])}个问题")
        
        risk_icon = "🟢" if risk_level == "低" else "🟡" if risk_level == "中" else "🔴"
        report_lines.append(f"{risk_icon} **风险等级: {risk_level}**")
        for reason in risk_reasons:
            report_lines.append(f"  - {reason}")
        report_lines.append("")
        
        # 警告信息
        if self.warnings:
            report_lines.extend([
                "## ⚠️ 扫描警告",
            ])
            for warning in self.warnings:
                report_lines.append(f"- {warning}")
            report_lines.append("")
        
        # 操作建议
        report_lines.extend([
            "## 💡 操作建议",
        ])
        
        if risk_level == "高":
            report_lines.append("1. 🔴 **立即处理**账户混淆风险文件")
            report_lines.append("2. 检查相关Skill配置的账户引用")
            report_lines.append("3. 确认后更新记忆文件")
        elif risk_level == "中":
            report_lines.append("1. 🟡 建议梳理配置文件中的账户引用")
            report_lines.append("2. 统一账户监控策略")
        else:
            report_lines.append("1. 🟢 系统账户隔离状态良好")
            report_lines.append("2. 建议保持当前的单一账户监控策略")
        
        report_lines.append("")
        
        # 配置文件编辑提示
        report_lines.extend([
            "## 📝 账户配置管理",
            "如需修改监控账户，请编辑:",
            f"```\n{CONFIG_FILE}\n```",
            "",
            "修改示例：",
            "```yaml",
            "monitored_accounts:",
            "  live:",
            "    profile: A5",
            "    status: disabled  # 改为 disabled 禁用，或 active 启用",
            "  demo:",
            "    profile: dreamdemo",
            "    status: active",
            "```",
            "",
            "---",
            f"*报告生成时间: {datetime.now().isoformat()}*",
        ])
        
        return "\n".join(report_lines)
    
    def update_account_status(self, account_type: str, status: str, note: str = ""):
        """更新账户状态"""
        if account_type not in self.config.get("monitored_accounts", {}):
            self.config.setdefault("monitored_accounts", {})[account_type] = {}
        
        self.config["monitored_accounts"][account_type]["status"] = status
        if note:
            self.config["monitored_accounts"][account_type]["note"] = note
        
        self.save_config(self.config)
        return f"✅ 已更新 {account_type} 状态为 {status}"


def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="账户隔离监控系统")
    parser.add_argument("--scan", action="store_true", help="执行全面扫描")
    parser.add_argument("--update", nargs=2, metavar=("ACCOUNT", "STATUS"), help="更新账户状态")
    parser.add_argument("--check", choices=["policy", "config", "reports"], help="单项检查")
    parser.add_argument("--output", "-o", help="输出报告文件路径")
    
    args = parser.parse_args()
    
    monitor = AccountMonitor()
    
    if args.update:
        account, status = args.update
        result = monitor.update_account_status(account, status)
        print(result)
        return
    
    if args.check:
        if args.check == "policy":
            policy = monitor.check_current_account_policy()
            print(json.dumps(policy, ensure_ascii=False, indent=2))
        elif args.check == "config":
            config = monitor.scan_config_files()
            print(json.dumps(config, ensure_ascii=False, indent=2))
        elif args.check == "reports":
            findings = monitor.scan_reports()
            print(json.dumps(findings, ensure_ascii=False, indent=2))
        return
    
    # 默认：执行全面扫描
    report = monitor.generate_report()
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已保存到: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
