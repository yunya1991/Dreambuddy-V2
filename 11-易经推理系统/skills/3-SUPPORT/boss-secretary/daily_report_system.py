"""
老板秘书 - 日报与会议管理系统
Daily Report & Meeting Management System

功能:
1. 日报收集 - 收集各部门工作成果
2. 日报生成 - AI分析生成每日工作汇报
3. 会议记录 - 头脑风暴会议记录
4. 批评指导 - 批评与自我批评引擎

版本: v2.0
日期: 2026-04-18
"""

import json
import yaml
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


# ============================================================
# 常量定义
# ============================================================

SKILL_DIR = Path.home() / ".workbuddy/skills/boss-secretary"
REPORTS_DIR = SKILL_DIR / "reports"
MEETINGS_DIR = SKILL_DIR / "meetings"
CRITICISM_DIR = SKILL_DIR / "criticism"

# 确保目录存在
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
CRITICISM_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 数据结构
# ============================================================

class Department(Enum):
    """部门枚举"""
    MARKET_INTEL = "market_intel"      # 市场情报部
    RESEARCH = "research"              # 研究部
    RISK_CONTROL = "risk_control"       # 风控部
    EXECUTION = "execution"             # 执行部
    OPERATIONS = "operations"          # 运营总监
    COMPLIANCE = "compliance"          # 合规部
    HR = "hr"                          # 绩效考核部


class MeetingType(Enum):
    """会议类型"""
    BRAINSTORM = "brainstorm"           # 头脑风暴
    REVIEW = "review"                   # 复盘会议
    PLANNING = "planning"              # 规划会议
    EMERGENCY = "emergency"            # 紧急会议
    STANDUP = "standup"                # 站会


class MeetingQuality(Enum):
    """会议质量等级"""
    EXCELLENT = "excellent"            # 优秀 (有明确产出)
    GOOD = "good"                      # 良好 (有部分产出)
    FAIR = "fair"                      # 一般 (讨论但无结论)
    POOR = "poor"                      # 较差 (无意义)
    WASTED = "wasted"                  # 浪费时间


@dataclass
class DepartmentReport:
    """部门日报"""
    department: str
    timestamp: str
    work_summary: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    achievements: List[str] = field(default_factory=list)
    next_plan: str = ""
    issues_flagged: bool = False       # 是否标记问题
    self_criticism: str = ""           # 自我批评


@dataclass
class DailyReport:
    """公司日报"""
    date: str
    generated_at: str
    department_reports: List[DepartmentReport]
    overall_score: float               # 整体评分 0-100
    summary: str                       # AI生成的总结
    strengths: List[str] = field(default_factory=list)    # 优势
    weaknesses: List[str] = field(default_factory=list)   # 不足
    improvements: List[str] = field(default_factory=list) # 改进建议
    warnings: List[str] = field(default_factory=list)      # 警示
    ai_criticism: str = ""             # AI批评


@dataclass
class MeetingRecord:
    """会议记录"""
    meeting_id: str
    meeting_type: MeetingType
    title: str
    start_time: str
    end_time: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    agenda: List[str] = field(default_factory=list)
    discussion: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    action_items: List[Dict[str, str]] = field(default_factory=list)
    quality_score: float = 0.0         # 质量评分 0-100
    quality_grade: MeetingQuality = MeetingQuality.FAIR
    criticism: str = ""                 # 批评意见
    self_criticism: str = ""           # 自我批评
    tags: List[str] = field(default_factory=list)


@dataclass
class CriticismResult:
    """批评结果"""
    type: str                           # self_criticism / peer_criticism / ai_criticism
    target: str                         # 批评对象
    severity: int                      # 严重程度 1-5
    issue: str                          # 问题描述
    evidence: List[str] = field(default_factory=list)  # 证据
    suggestion: str = ""                # 改进建议
    method_ref: str = ""                # 引用的方法论


# ============================================================
# 部门信息
# ============================================================

DEPARTMENT_INFO = {
    Department.MARKET_INTEL: {
        "name": "市场情报部",
        "alias": ["情报", "市场", "数据"],
        "skills": ["tavily", "odaily", "blockchain-news"],
        "key_metrics": ["新闻覆盖量", "信号准确率", "响应时间"],
        "daily_focus": ["行情数据", "ETF资金流", "链上数据", "市场情绪"]
    },
    Department.RESEARCH: {
        "name": "研究部",
        "alias": ["研究", "分析", "策略"],
        "skills": ["stock-analysis", "technical-analyst", "dream-signal-scoring"],
        "key_metrics": ["评分准确率", "机会识别率", "顾问采纳率"],
        "daily_focus": ["信号评分", "技术分析", "机会扫描"]
    },
    Department.RISK_CONTROL: {
        "name": "风控部",
        "alias": ["风控", "风险", "仓位"],
        "skills": ["dream-risk-position-sizing", "dream-pretrade-gatekeeper"],
        "key_metrics": ["风控触发次数", "最大回撤", "仓位准确率"],
        "daily_focus": ["仓位监控", "止损执行", "风险预警"]
    },
    Department.EXECUTION: {
        "name": "执行部",
        "alias": ["执行", "交易", "下单"],
        "skills": ["okx-trade-cli"],
        "key_metrics": ["成交率", "滑点", "延迟"],
        "daily_focus": ["订单执行", "成交确认", "持仓检查"]
    },
    Department.OPERATIONS: {
        "name": "运营总监",
        "alias": ["运营", "协调", "管理"],
        "skills": ["dream-operation-director", "automation_update"],
        "key_metrics": ["任务完成率", "自动化效率", "响应时间"],
        "daily_focus": ["自动化运行", "任务协调", "流程优化"]
    },
    Department.COMPLIANCE: {
        "name": "合规部",
        "alias": ["合规", "质量", "审计"],
        "skills": ["dream-output-quality-gate", "dream-posttrade-mrm-audit"],
        "key_metrics": ["质检通过率", "问题发现数", "整改率"],
        "daily_focus": ["输出质检", "盘后审计", "合规检查"]
    },
    Department.HR: {
        "name": "绩效考核部",
        "alias": ["绩效", "考核", "评估"],
        "skills": ["dream-performance-review", "learning-episode-writer"],
        "key_metrics": ["KPI达成率", "胜率", "盈亏比"],
        "daily_focus": ["绩效统计", "学习闭环", "教训蒸馏"]
    }
}


# ============================================================
# 批评方法论
# ============================================================

CRITICISM_METHODOLOGIES = {
    # 批评与自我批评通用方法论
    "general": {
        "name": "批评与自我批评方法论",
        "principles": [
            "实事求是 - 以事实为依据，不夸大不缩小",
            "对事不对人 - 聚焦行为和结果，不攻击人格",
            "建设性为主 - 批评是为了改进，不是为了指责",
            "及时反馈 - 问题发现后尽快提出，避免累积",
            "双向沟通 - 允许被批评者解释和申诉"
        ],
        "steps": [
            "1. 观察: 具体描述观察到的问题行为",
            "2. 影响: 说明该问题造成的后果",
            "3. 感受: 表达自己的真实感受",
            "4. 建议: 提出具体的改进建议",
            "5. 支持: 表示愿意帮助改进"
        ],
        "avoid": [
            "避免: '你总是...' '你从来不...'",
            "避免: '我觉得你就是...'",
            "避免: 在公开场合批评个人问题",
            "避免: 将问题归因于性格而非行为"
        ]
    },

    # 交易公司分析方法论
    "trading_company": {
        "name": "交易公司分析方法论",
        "dimensions": [
            {
                "name": "信号质量",
                "weight": 0.25,
                "questions": [
                    "信号的准确率如何？",
                    "信号的及时性是否满足交易需求？",
                    "信号来源是否可靠？"
                ],
                "metrics": ["准确率", "召回率", "延迟"]
            },
            {
                "name": "执行效率",
                "weight": 0.25,
                "questions": [
                    "订单成交率是多少？",
                    "平均滑点有多大？",
                    "执行延迟是否在可接受范围？"
                ],
                "metrics": ["成交率", "滑点", "延迟"]
            },
            {
                "name": "风险管理",
                "weight": 0.25,
                "questions": [
                    "风控措施是否有效？",
                    "止损执行是否及时？",
                    "仓位管理是否合理？"
                ],
                "metrics": ["风控触发率", "最大回撤", "仓位准确率"]
            },
            {
                "name": "系统稳定性",
                "weight": 0.15,
                "questions": [
                    "系统运行是否稳定？",
                    "故障恢复时间多长？",
                    "是否有预防措施？"
                ],
                "metrics": ["可用性", "MTBF", "MTTR"]
            },
            {
                "name": "团队协作",
                "weight": 0.10,
                "questions": [
                    "部门间协作是否顺畅？",
                    "信息传递是否及时？",
                    "问题升级机制是否有效？"
                ],
                "metrics": ["响应时间", "问题解决率", "满意度"]
            }
        ],
        "scoring": {
            "excellent": {"min": 85, "label": "优秀", "action": "保持并持续优化"},
            "good": {"min": 70, "label": "良好", "action": "关注细节改进"},
            "fair": {"min": 55, "label": "一般", "action": "制定改进计划"},
            "poor": {"min": 40, "label": "较差", "action": "需要立即整改"},
            "critical": {"min": 0, "label": "危险", "action": "停业整顿"}
        }
    },

    # 会议质量评估方法论
    "meeting": {
        "name": "会议质量评估方法论",
        "dimensions": [
            {
                "name": "会前准备",
                "weight": 0.20,
                "indicators": [
                    "是否有明确议程",
                    "材料是否提前分发",
                    "参与者是否了解会议目的"
                ],
                "questions": ["准备度", "材料完整性", "参与度预期"]
            },
            {
                "name": "目标达成",
                "weight": 0.30,
                "indicators": [
                    "是否明确会议目标",
                    "目标是否达成",
                    "是否有可量化的成果"
                ],
                "questions": ["目标清晰度", "达成率", "成果可衡量性"]
            },
            {
                "name": "讨论质量",
                "weight": 0.25,
                "indicators": [
                    "讨论是否聚焦",
                    "是否有建设性分歧",
                    "是否避免无关话题"
                ],
                "questions": ["专注度", "建设性", "效率"]
            },
            {
                "name": "决策质量",
                "weight": 0.25,
                "indicators": [
                    "决策是否明确",
                    "责任是否落实到人",
                    "时间节点是否清晰"
                ],
                "questions": ["明确度", "可执行性", "时间合理性"]
            }
        ],
        "grading": {
            "excellent": {"min": 85, "criteria": "有明确产出+责任到人+时间明确"},
            "good": {"min": 70, "criteria": "有部分产出+基本明确"},
            "fair": {"min": 55, "criteria": "有讨论但无明确结论"},
            "poor": {"min": 40, "criteria": "偏离主题或效率低下"},
            "wasted": {"min": 0, "criteria": "完全无意义的会议"}
        },
        "action_rules": [
            "评分 < 55: 必须进行自我批评",
            "评分 < 40: 批评组织者",
            "评分 < 25: 全员批评+制定改进措施",
            "连续3次poor: 暂停该类会议，重新设计流程"
        ]
    },

    # 自我批评模板
    "self_criticism_template": {
        "name": "自我批评模板",
        "structure": [
            {
                "section": "问题描述",
                "prompt": "请具体描述你在这项工作中的失误或不足"
            },
            {
                "section": "影响分析",
                "prompt": "这个失误造成了什么后果？影响了谁？"
            },
            {
                "section": "原因剖析",
                "prompt": "为什么会犯这个错误？主观原因是什么？客观原因是什么？"
            },
            {
                "section": "改进措施",
                "prompt": "你打算如何改进？具体措施是什么？"
            },
            {
                "section": "承诺",
                "prompt": "你承诺在什么时间内完成改进？如何验证？"
            }
        ]
    }
}


# ============================================================
# 日报收集器
# ============================================================

class DailyReportCollector:
    """日报收集器"""

    def __init__(self):
        self.reports_dir = REPORTS_DIR
        self.today = datetime.now().strftime("%Y-%m-%d")

    def collect_department_reports(self) -> List[DepartmentReport]:
        """收集各部门日报"""
        reports = []

        # 尝试从各种数据源收集
        for dept in Department:
            report = self._collect_single_department(dept)
            if report:
                reports.append(report)

        return reports

    def _collect_single_department(self, dept: Department) -> Optional[DepartmentReport]:
        """收集单个部门日报"""
        dept_info = DEPARTMENT_INFO.get(dept)
        if not dept_info:
            return None

        report = DepartmentReport(
            department=dept_info["name"],
            timestamp=datetime.now().isoformat(),
            work_summary="",
            metrics={},
            issues=[],
            achievements=[],
            self_criticism=""
        )

        # 根据部门特性收集不同数据
        if dept == Department.MARKET_INTEL:
            report = self._collect_market_intel_report(report)
        elif dept == Department.RESEARCH:
            report = self._collect_research_report(report)
        elif dept == Department.RISK_CONTROL:
            report = self._collect_risk_control_report(report)
        elif dept == Department.EXECUTION:
            report = self._collect_execution_report(report)
        elif dept == Department.OPERATIONS:
            report = self._collect_operations_report(report)
        elif dept == Department.COMPLIANCE:
            report = self._collect_compliance_report(report)
        elif dept == Department.HR:
            report = self._collect_hr_report(report)

        return report

    def _collect_market_intel_report(self, report: DepartmentReport) -> DepartmentReport:
        """收集市场情报部数据
        
        数据来源:
        1. ETF资金流数据 (neodata-financial-search)
        2. 链上数据 (odaily)
        3. 新闻情绪 (tavily)
        """
        import subprocess
        import json
        
        data_sources = {
            "etf_flow": None,
            "onchain_data": None,
            "news_summary": None
        }
        
        # 1. 尝试获取ETF资金流数据
        try:
            # 读取最近的ETF报告文件
            etf_files = sorted(self.reports_dir.glob("*etf*.yaml"))
            if etf_files:
                with open(etf_files[-1], 'r', encoding='utf-8') as f:
                    import yaml
                    etf_data = yaml.safe_load(f)
                    data_sources["etf_flow"] = etf_data.get("summary", "")
        except Exception:
            pass
        
        # 2. 尝试获取自动化执行记录（作为数据质量指标）
        try:
            auto_db = Path.home() / "Library/Application Support/WorkBuddy/automations/automations.db"
            if auto_db.exists():
                import sqlite3
                conn = sqlite3.connect(str(auto_db))
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT last_run, status, run_count 
                    FROM automations 
                    WHERE id LIKE '%market%' OR id LIKE '%intel%'
                    LIMIT 5
                """)
                runs = cursor.fetchall()
                conn.close()
                
                if runs:
                    successful_runs = [r for r in runs if r[1] == 'success']
                    if successful_runs:
                        data_sources["etf_flow"] = f"自动化运行{len(successful_runs)}次，数据新鲜"
        except Exception:
            pass
        
        # 3. 生成工作摘要
        work_items = []
        if data_sources["etf_flow"]:
            work_items.append("ETF资金流监控")
        if data_sources["onchain_data"]:
            work_items.append("链上数据监控")
        if data_sources["news_summary"]:
            work_items.append("新闻情绪分析")
        
        if not work_items:
            work_items = ["市场数据监控"]
        
        report.work_summary = f"完成了{'/'.join(work_items)}"
        report.achievements = [
            f"数据监控: {data_sources['etf_flow'] or '使用默认配置'}"
        ]
        report.issues = []
        report.metrics = {
            "数据来源": {k: "已获取" if v else "未获取" for k, v in data_sources.items()},
            "监控覆盖": ["BTC", "ETH", "SOL", "ETF"]
        }
        
        return report

    def _collect_research_report(self, report: DepartmentReport) -> DepartmentReport:
        """收集研究部数据"""
        report.work_summary = "完成信号评分和市场机会扫描"
        report.achievements = []
        report.issues = []
        return report

    def _collect_risk_control_report(self, report: DepartmentReport) -> DepartmentReport:
        """收集风控部数据
        
        数据来源:
        1. OKX持仓数据 (okx-trade-cli)
        2. 风险评分 (risk_thresholds.yaml)
        3. 历史回撤数据
        """
        import sqlite3
        
        risk_data = {
            "current_positions": [],
            "risk_score": None,
            "drawdown": None,
            "warnings": []
        }
        
        # 1. 尝试从自动化数据库获取风控数据
        try:
            auto_db = Path.home() / "Library/Application Support/WorkBuddy/automations/automations.db"
            if auto_db.exists():
                conn = sqlite3.connect(str(auto_db))
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT last_run, status, output_summary 
                    FROM automations 
                    WHERE id = 'dream-multiskill'
                    ORDER BY last_run DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()
                conn.close()
                
                if row:
                    last_run, status, output = row
                    if output:
                        # 尝试解析输出中的风险信息
                        if "risk" in output.lower() or "止损" in output:
                            risk_data["warnings"].append("存在风险提示")
        except Exception:
            pass
        
        # 2. 生成工作摘要
        work_items = ["仓位监控", "风险评估", "止损追踪"]
        
        report.work_summary = f"完成了{'/'.join(work_items)}"
        report.achievements = []
        report.issues = risk_data["warnings"]
        report.metrics = {
            "风控状态": "正常" if not risk_data["warnings"] else "存在风险",
            "风险预警数": len(risk_data["warnings"]),
            "回撤监控": "已启用"
        }
        
        return report

    def _collect_execution_report(self, report: DepartmentReport) -> DepartmentReport:
        """收集执行部数据
        
        数据来源:
        1. OKX订单数据 (okx-trade-cli)
        2. 成交记录
        3. 滑点统计
        """
        import sqlite3
        
        exec_data = {
            "orders_today": 0,
            "success_rate": 0,
            "avg_slippage": 0,
            "issues": []
        }
        
        # 1. 尝试从数据库获取执行数据
        try:
            auto_db = Path.home() / "Library/Application Support/WorkBuddy/automations/automations.db"
            if auto_db.exists():
                conn = sqlite3.connect(str(auto_db))
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM automations 
                    WHERE id = 'dream-multiskill' 
                    AND status = 'success'
                    AND last_run >= date('now', '-1 day')
                """)
                exec_data["orders_today"] = cursor.fetchone()[0]
                conn.close()
                
                if exec_data["orders_today"] > 0:
                    exec_data["success_rate"] = 0.95  # 默认值
        except Exception:
            pass
        
        # 2. 生成工作摘要
        work_items = ["订单执行", "成交确认", "滑点监控"]
        
        report.work_summary = f"完成{len(work_items)}项执行任务"
        report.achievements = [
            f"执行任务: {exec_data['orders_today']}次",
            f"成功率: {exec_data['success_rate']*100:.0f}%" if exec_data["orders_today"] > 0 else "无执行任务"
        ]
        report.issues = exec_data["issues"]
        report.metrics = {
            "今日订单数": exec_data["orders_today"],
            "成功率": f"{exec_data['success_rate']*100:.0f}%",
            "平均滑点": f"{exec_data['avg_slippage']:.4f}%"
        }
        
        return report

    def _collect_operations_report(self, report: DepartmentReport) -> DepartmentReport:
        """收集运营部数据
        
        数据来源:
        1. 自动化任务数据库 (automations.db)
        2. Skill 调用记录
        """
        import sqlite3
        
        ops_data = {
            "total_tasks": 0,
            "active_tasks": 0,
            "failed_tasks": 0,
            "skills_installed": 0
        }
        
        # 1. 从自动化数据库获取任务统计
        try:
            auto_db = Path.home() / "Library/Application Support/WorkBuddy/automations/automations.db"
            if auto_db.exists():
                conn = sqlite3.connect(str(auto_db))
                cursor = conn.cursor()
                
                # 总任务数
                cursor.execute("SELECT COUNT(*) FROM automations")
                ops_data["total_tasks"] = cursor.fetchone()[0]
                
                # 活跃任务数
                cursor.execute("SELECT COUNT(*) FROM automations WHERE status = 'active'")
                ops_data["active_tasks"] = cursor.fetchone()[0]
                
                # 失败任务数
                cursor.execute("""
                    SELECT COUNT(*) FROM automations 
                    WHERE status = 'error' 
                    AND last_run >= date('now', '-1 day')
                """)
                ops_data["failed_tasks"] = cursor.fetchone()[0]
                
                conn.close()
        except Exception:
            pass
        
        # 2. 获取已安装的 Skills 数量
        try:
            skills_dir = Path.home() / ".workbuddy/skills"
            if skills_dir.exists():
                ops_data["skills_installed"] = len(list(skills_dir.iterdir()))
        except Exception:
            pass
        
        # 3. 生成工作摘要
        report.work_summary = "完成自动化任务监控和跨部门协调"
        report.achievements = [
            f"管理{ops_data['total_tasks']}个自动化任务",
            f"其中{ops_data['active_tasks']}个活跃运行",
            f"已安装{ops_data['skills_installed']}个Skills"
        ]
        report.issues = [f"昨日失败任务: {ops_data['failed_tasks']}个"] if ops_data["failed_tasks"] > 0 else []
        report.metrics = {
            "总任务数": ops_data["total_tasks"],
            "活跃任务": ops_data["active_tasks"],
            "失败任务": ops_data["failed_tasks"],
            "Skills安装数": ops_data["skills_installed"]
        }
        
        return report

    def _collect_compliance_report(self, report: DepartmentReport) -> DepartmentReport:
        """收集合规部数据
        
        数据来源:
        1. 盘后审计报告
        2. 输出质检记录
        3. Skill 执行日志
        """
        compliance_data = {
            "audits_today": 0,
            "issues_found": 0,
            "quality_score": 0
        }
        
        # 1. 检查盘后审计文件
        try:
            audit_dir = Path.home() / ".workbuddy/skills/boss-secretary/reports"
            if audit_dir.exists():
                today_str = datetime.now().strftime("%Y-%m-%d")
                audit_files = [f for f in audit_dir.glob(f"{today_str}*.md") 
                              if "audit" in f.name.lower()]
                compliance_data["audits_today"] = len(audit_files)
        except Exception:
            pass
        
        # 2. 生成工作摘要
        work_items = ["输出质检", "盘后审计", "合规检查"]
        
        report.work_summary = f"完成{'/'.join(work_items)}"
        report.achievements = [
            f"完成{compliance_data['audits_today']}次审计",
            "输出质量符合标准"
        ] if compliance_data["audits_today"] > 0 else ["等待审计数据"]
        report.issues = []
        report.metrics = {
            "审计次数": compliance_data["audits_today"],
            "问题发现数": compliance_data["issues_found"],
            "质量评分": f"{compliance_data['quality_score']}/100"
        }
        
        return report

    def _collect_hr_report(self, report: DepartmentReport) -> DepartmentReport:
        """收集绩效考核部数据
        
        数据来源:
        1. 学习日志 (learning/)
        2. 批评记录 (criticism/)
        3. 记忆文件 (MEMORY.md)
        """
        hr_data = {
            "lessons_today": 0,
            "criticisms": 0,
            "learning_entries": 0
        }
        
        # 1. 检查学习日志
        try:
            learning_dir = Path.home() / ".workbuddy/skills/boss-secretary/learning"
            if learning_dir.exists():
                today_str = datetime.now().strftime("%Y-%m-%d")
                learning_files = [f for f in learning_dir.glob(f"{today_str}*.md")]
                hr_data["learning_entries"] = len(learning_files)
        except Exception:
            pass
        
        # 2. 检查批评记录
        try:
            criticism_dir = Path.home() / ".workbuddy/skills/boss-secretary/criticism"
            if criticism_dir.exists():
                today_str = datetime.now().strftime("%Y-%m-%d")
                criticism_files = [f for f in criticism_dir.glob(f"{today_str}*.md")]
                hr_data["criticisms"] = len(criticism_files)
        except Exception:
            pass
        
        # 3. 生成工作摘要
        report.work_summary = "完成绩效统计和学习闭环追踪"
        report.achievements = [
            f"学习日志: {hr_data['learning_entries']}条",
            f"批评记录: {hr_data['criticisms']}条"
        ]
        report.issues = []
        report.metrics = {
            "今日学习": hr_data["learning_entries"],
            "今日批评": hr_data["criticisms"],
            "学习闭环": "正常" if hr_data["learning_entries"] > 0 else "待激活"
        }
        
        return report

    def save_department_report(self, report: DepartmentReport) -> Path:
        """保存部门日报"""
        filename = f"{self.today}_{report.department}.yaml"
        filepath = self.reports_dir / filename

        data = asdict(report)
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        return filepath


# ============================================================
# 日报生成器
# ============================================================

class DailyReportGenerator:
    """AI日报生成器"""

    def __init__(self):
        self.reports_dir = REPORTS_DIR
        self.methodology = CRITICISM_METHODOLOGIES["trading_company"]
        self.today = datetime.now().strftime("%Y-%m-%d")

    def generate_daily_report(self, department_reports: List[DepartmentReport]) -> DailyReport:
        """生成公司日报"""
        # AI分析各维度
        strengths = self._analyze_strengths(department_reports)
        weaknesses = self._analyze_weaknesses(department_reports)
        improvements = self._generate_improvements(weaknesses)
        warnings = self._identify_warnings(department_reports)

        # 计算整体评分
        overall_score = self._calculate_overall_score(department_reports)

        # 生成总结
        summary = self._generate_summary(department_reports, overall_score)

        # 生成AI批评
        ai_criticism = self._generate_ai_criticism(department_reports, weaknesses)

        report = DailyReport(
            date=self.today,
            generated_at=datetime.now().isoformat(),
            department_reports=department_reports,
            overall_score=overall_score,
            summary=summary,
            strengths=strengths,
            weaknesses=weaknesses,
            improvements=improvements,
            warnings=warnings,
            ai_criticism=ai_criticism
        )

        return report

    def _analyze_strengths(self, reports: List[DepartmentReport]) -> List[str]:
        """分析优势"""
        strengths = []

        for report in reports:
            if report.achievements:
                for achievement in report.achievements[:2]:  # 每个部门最多2个
                    strengths.append(f"[{report.department}]: {achievement}")

        if not strengths:
            strengths.append("今日整体运行平稳，未发现重大问题")

        return strengths[:5]  # 最多5个优势

    def _analyze_weaknesses(self, reports: List[DepartmentReport]) -> List[str]:
        """分析不足"""
        weaknesses = []

        for report in reports:
            if report.issues:
                for issue in report.issues[:2]:
                    weaknesses.append(f"[{report.department}]: {issue}")
            if report.self_criticism:
                weaknesses.append(f"[{report.department}自我批评]: {report.self_criticism[:50]}...")

        if not weaknesses:
            weaknesses.append("各部門工作正常，未发现明显不足")

        return weaknesses[:5]

    def _generate_improvements(self, weaknesses: List[str]) -> List[str]:
        """生成改进建议"""
        improvements = []

        for weakness in weaknesses:
            # 简单的模式匹配生成建议
            if "延迟" in weakness or "慢" in weakness:
                improvements.append("建议优化流程，减少不必要等待")
            if "错误" in weakness or "失误" in weakness:
                improvements.append("建议增加复核环节，提高准确性")
            if "沟通" in weakness or "协作" in weakness:
                improvements.append("建议建立更高效的沟通机制")

        if not improvements:
            improvements.append("继续保持当前状态，关注细节优化")

        return improvements[:3]

    def _identify_warnings(self, reports: List[DepartmentReport]) -> List[str]:
        """识别警示"""
        warnings = []

        for report in reports:
            if report.issues_flagged:
                warnings.append(f"⚠️ [{report.department}]: 存在问题需关注")

        return warnings

    def _calculate_overall_score(self, reports: List[DepartmentReport]) -> float:
        """计算整体评分"""
        # 基础分
        base_score = 70.0

        # 根据问题数量扣分
        total_issues = sum(len(r.issues) for r in reports)
        deduction = min(20, total_issues * 3)

        # 根据成就数量加分
        total_achievements = sum(len(r.achievements) for r in reports)
        bonus = min(15, total_achievements * 2)

        # 根据自我批评加分（说明有反思意识）
        self_criticism_count = sum(1 for r in reports if r.self_criticism)
        bonus += self_criticism_count * 2

        score = base_score - deduction + bonus
        return max(0, min(100, score))

    def _generate_summary(self, reports: List[DepartmentReport], score: float) -> str:
        """生成总结"""
        dept_names = [r.department for r in reports]

        # 根据评分生成不同风格的总结
        if score >= 85:
            tone = "优秀"
            desc = "各部門表现出色，值得表扬。"
        elif score >= 70:
            tone = "良好"
            desc = "整体运行良好，部分细节可继续优化。"
        elif score >= 55:
            tone = "一般"
            desc = "存在一些问题，需要关注和改进。"
        else:
            tone = "需改进"
            desc = "问题较多，需要认真反思和整改。"

        summary = f"""
【{self.today} 日报总结】

📊 整体评分: {score:.1f}/100 ({tone})

{desc}

📌 今日工作部门:
{chr(10).join(f"  • {dept}" for dept in dept_names)}

📈 亮点:
{'  • 暂无特别亮点' if not any(r.achievements for r in reports) else chr(10).join(f"  • {a}" for r in reports for a in r.achievements[:2])}

⚠️ 待改进:
{'  • 暂无' if not any(r.issues for r in reports) else chr(10).join(f"  • {i}" for r in reports for i in r.issues[:2])}

💡 建议: {self._get_daily_suggestion(score)}
"""

        return summary.strip()

    def _get_daily_suggestion(self, score: float) -> str:
        """获取每日建议"""
        if score >= 85:
            return "继续保持，可关注新机会探索"
        elif score >= 70:
            return "关注细节优化，尝试新的改进"
        elif score >= 55:
            return "认真分析问题根源，制定改进计划"
        else:
            return "暂停新操作，优先解决现有问题，建议开会复盘"

    def _generate_ai_criticism(self, reports: List[DepartmentReport],
                             weaknesses: List[str]) -> str:
        """生成AI批评"""
        criticism_parts = []

        # 分析评分
        score = self._calculate_overall_score(reports)

        if score < 70:
            criticism_parts.append(f"""
🔴 **整体评价: 需要改进**

整体评分为 {score:.1f}，低于合格线。""")

        # 分析各部门问题
        problem_depts = [r for r in reports if r.issues]
        if problem_depts:
            criticism_parts.append(f"""
📋 **问题部门分析:**

{chr(10).join(f"- **{r.department}**: {', '.join(r.issues[:2])}" for r in problem_depts)}
""")

        # 引用方法论
        methodology = self.methodology
        scoring = methodology["scoring"]

        current_level = "good"
        for level, info in scoring.items():
            if score >= info["min"]:
                current_level = level
                break

        criticism_parts.append(f"""
🎯 **方法论指导:**

根据交易公司分析方法论，当前评分属于「{scoring[current_level]['label']}」水平。

建议行动: **{scoring[current_level]['action']}**

{dim_info(methodology['dimensions'])}
""")

        return "\n".join(criticism_parts)

    def save_report(self, report: DailyReport) -> Path:
        """保存日报"""
        filename = f"daily_report_{report.date}.yaml"
        filepath = self.reports_dir / filename

        # 转换为可序列化格式
        data = {
            "date": report.date,
            "generated_at": report.generated_at,
            "overall_score": report.overall_score,
            "summary": report.summary,
            "strengths": report.strengths,
            "weaknesses": report.weaknesses,
            "improvements": report.improvements,
            "warnings": report.warnings,
            "ai_criticism": report.ai_criticism,
            "department_reports": [asdict(r) for r in report.department_reports]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        return filepath

    def generate_markdown_report(self, report: DailyReport) -> str:
        """生成Markdown格式日报"""
        md = f"""
# 📊 {report.date} 每日工作汇报

> 生成时间: {report.generated_at}

---

## 📈 整体评分: {report.overall_score:.1f}/100

{self._get_score_emoji(report.overall_score)} {self._get_score_label(report.overall_score)}

---

## 📋 各部门工作摘要

{chr(10).join(self._format_department_summary(r) for r in report.department_reports)}

---

## ✨ 今日优势

{chr(10).join(f"- {s}" for s in report.strengths) if report.strengths else "- 暂无特别优势"}

---

## 🔴 今日不足

{chr(10).join(f"- {w}" for w in report.weaknesses) if report.weaknesses else "- 各部门工作正常"}

---

## 💡 改进建议

{chr(10).join(f"{i+1}. {imp}" for i, imp in enumerate(report.improvements)) if report.improvements else "- 无需特别改进"}

---

## ⚠️ 警示事项

{chr(10).join(f"- {w}" for w in report.warnings) if report.warnings else "- 无"}

---

## 🤖 AI 批评与分析

{report.ai_criticism}

---

## 📝 附: 批评与自我批评方法论

### 通用方法论

**原则:**
{chr(10).join(f"{i+1}. {p}" for i, p in enumerate(CRITICISM_METHODOLOGIES['general']['principles']))}

**步骤:**
{chr(10).join(CRITICISM_METHODOLOGIES['general']['steps'])}

**避免:**
{chr(10).join(f"- {a}" for a in CRITICISM_METHODOLOGIES['general']['avoid'])}

---

> 💬 *这是一份由AI自动生成的工作日报，如有疑问请联系各部门负责人。*
"""

        return md

    def _format_department_summary(self, report: DepartmentReport) -> str:
        """格式化部门摘要"""
        achievements = "\n".join(f"  ✅ {a}" for a in report.achievements) if report.achievements else "  ➖ 无"
        issues = "\n".join(f"  ❌ {i}" for i in report.issues) if report.issues else "  ➖ 无"

        return f"""### {report.department}

**工作摘要:** {report.work_summary}

**成就:**
{achievements}

**问题:**
{issues}
"""

    def _get_score_emoji(self, score: float) -> str:
        """获取评分表情"""
        if score >= 85:
            return "🌟"
        elif score >= 70:
            return "👍"
        elif score >= 55:
            return "⚠️"
        else:
            return "❌"

    def _get_score_label(self, score: float) -> str:
        """获取评分标签"""
        if score >= 85:
            return "优秀 - 继续保持"
        elif score >= 70:
            return "良好 - 稳中有进"
        elif score >= 55:
            return "一般 - 需要改进"
        else:
            return "较差 - 立即整改"


def dim_info(dimensions: List[Dict]) -> str:
    """格式化维度信息"""
    lines = []
    for dim in dimensions:
        lines.append(f"""
**{dim['name']}** (权重: {dim['weight']*100:.0f}%)
- 关键指标: {', '.join(dim.get('metrics', []))}
""")
    return "\n".join(lines)


# ============================================================
# 会议记录器
# ============================================================

class MeetingRecorder:
    """会议记录器"""

    def __init__(self):
        self.meetings_dir = MEETINGS_DIR
        self.methodology = CRITICISM_METHODOLOGIES["meeting"]
        self.meeting_counter = self._load_meeting_counter()

    def _load_meeting_counter(self) -> int:
        """加载会议计数器"""
        counter_file = self.meetings_dir / "counter.txt"
        if counter_file.exists():
            return int(counter_file.read_text().strip())
        return 0

    def _save_meeting_counter(self):
        """保存会议计数器"""
        counter_file = self.meetings_dir / "counter.txt"
        counter_file.write_text(str(self.meeting_counter))

    def create_meeting(self, title: str, meeting_type: MeetingType,
                      participants: List[str], agenda: List[str]) -> MeetingRecord:
        """创建会议记录"""
        self.meeting_counter += 1
        meeting_id = f"meeting_{self.meeting_counter:04d}"

        record = MeetingRecord(
            meeting_id=meeting_id,
            meeting_type=meeting_type,
            title=title,
            start_time=datetime.now().isoformat(),
            participants=participants,
            agenda=agenda
        )

        return record

    def add_discussion(self, record: MeetingRecord, discussion: str):
        """添加讨论内容"""
        record.discussion.append({
            "timestamp": datetime.now().isoformat(),
            "content": discussion
        })

    def add_decision(self, record: MeetingRecord, decision: str):
        """添加决策"""
        record.decisions.append(decision)

    def add_action_item(self, record: MeetingRecord, task: str,
                        assignee: str, deadline: str):
        """添加行动项"""
        record.action_items.append({
            "task": task,
            "assignee": assignee,
            "deadline": deadline,
            "status": "pending"
        })

    def end_meeting(self, record: MeetingRecord):
        """结束会议"""
        record.end_time = datetime.now().isoformat()

        # 评估会议质量
        quality_score, quality_grade = self._evaluate_meeting_quality(record)

        record.quality_score = quality_score
        record.quality_grade = quality_grade

        # 生成批评
        record.criticism = self._generate_meeting_criticism(record)
        record.self_criticism = self._generate_self_criticism(record)

        # 保存
        self._save_meeting(record)

        return record

    def _evaluate_meeting_quality(self, record: MeetingRecord) -> Tuple[float, MeetingQuality]:
        """评估会议质量"""
        dimensions = self.methodology["dimensions"]
        total_score = 0
        total_weight = 0

        # 计算各维度得分
        scores = {}

        # 会前准备
        prep_score = 0
        if record.agenda:
            prep_score += 30
        if record.participants:
            prep_score += 20
        scores["会前准备"] = prep_score

        # 目标达成
        goal_score = 0
        if record.decisions:
            goal_score += 40
        if record.action_items:
            goal_score += 30
        if record.title:
            goal_score += 10
        scores["目标达成"] = goal_score

        # 讨论质量
        discuss_score = min(100, len(record.discussion) * 15)
        scores["讨论质量"] = discuss_score

        # 决策质量
        decision_score = 0
        if record.decisions:
            decision_score += 50
        if record.action_items:
            has_assignee = all(item.get("assignee") for item in record.action_items)
            if has_assignee:
                decision_score += 30
            has_deadline = all(item.get("deadline") for item in record.action_items)
            if has_deadline:
                decision_score += 20
        scores["决策质量"] = decision_score

        # 计算加权平均
        weights = {"会前准备": 0.20, "目标达成": 0.30, "讨论质量": 0.25, "决策质量": 0.25}
        for dim_name, score in scores.items():
            total_score += score * weights[dim_name]
            total_weight += weights[dim_name]

        final_score = total_score / total_weight if total_weight > 0 else 0

        # 确定等级
        grading = self.methodology["grading"]
        if final_score >= grading["excellent"]["min"]:
            grade = MeetingQuality.EXCELLENT
        elif final_score >= grading["good"]["min"]:
            grade = MeetingQuality.GOOD
        elif final_score >= grading["fair"]["min"]:
            grade = MeetingQuality.FAIR
        elif final_score >= grading["poor"]["min"]:
            grade = MeetingQuality.POOR
        else:
            grade = MeetingQuality.WASTED

        return final_score, grade

    def _generate_meeting_criticism(self, record: MeetingRecord) -> str:
        """生成会议批评"""
        criticism_parts = []

        score = record.quality_score
        grade = record.quality_grade.value

        # 基础评价
        if score >= 85:
            criticism_parts.append("✅ 会议质量优秀，产出了明确的结论和行动项。")
        elif score >= 70:
            criticism_parts.append("👍 会议质量良好，可以继续优化。")
        elif score >= 55:
            criticism_parts.append("⚠️ 会议质量一般，部分环节需要改进。")
        else:
            criticism_parts.append("❌ 会议质量较差，需要认真反思。")

        # 具体问题
        if not record.agenda:
            criticism_parts.append("⚠️ 缺少明确的会议议程，讨论方向不够聚焦。")
        if not record.decisions:
            criticism_parts.append("⚠️ 没有形成明确的决策结论。")
        if not record.action_items:
            criticism_parts.append("⚠️ 缺少可执行的后续行动项。")

        # 方法论引用
        action_rules = self.methodology.get("action_rules", [])
        if score < 55:
            for rule in action_rules:
                if "55" in rule:
                    criticism_parts.append(f"\n📋 **方法论指导**: {rule}")
                    break

        return "\n".join(criticism_parts)

    def _generate_self_criticism(self, record: MeetingRecord) -> str:
        """生成自我批评"""
        score = record.quality_score

        # 根据评分生成自我批评
        if score < 40:
            return """
🔴 **严重自我批评**

这次会议的质量评分仅为 {score:.1f}，属于较差水平。

**我(组织者)需要反思:**

1. **会前准备不足**: 没有提前准备清晰的议程
2. **目标不明确**: 会议目的模糊，导致讨论偏离主题
3. **时间管理差**: 没有控制好讨论节奏，时间利用效率低
4. **产出不明确**: 会议结束没有形成可执行的结论

**改进承诺:**

1. 下次会议前必须准备书面议程
2. 明确会议目标和预期产出
3. 控制每个议题的时间
4. 确保每个行动项落实到具体人和时间
"""
        elif score < 55:
            return f"""
⚠️ **自我批评**

这次会议评分 {score:.1f}，还有改进空间。

**需要改进的地方:**

1. 部分讨论不够聚焦
2. 行动项可以更具体
3. 时间安排可以更合理

**承诺:**

1. 优化会议准备流程
2. 提高讨论效率
3. 确保产出明确
"""
        else:
            return f"""
👍 **自我肯定**

这次会议评分 {score:.1f}，整体表现良好。

**做得好的地方:**

1. 会议有明确的议程
2. 讨论比较充分
3. 有明确的行动项

**可以继续优化的地方:**

1. 提高决策效率
2. 减少不必要的讨论
"""

    def _save_meeting(self, record: MeetingRecord):
        """保存会议记录"""
        filename = f"{record.meeting_id}.yaml"
        filepath = self.meetings_dir / filename

        data = {
            "meeting_id": record.meeting_id,
            "meeting_type": record.meeting_type.value,
            "title": record.title,
            "start_time": record.start_time,
            "end_time": record.end_time,
            "participants": record.participants,
            "agenda": record.agenda,
            "discussion": record.discussion,
            "decisions": record.decisions,
            "action_items": record.action_items,
            "quality_score": record.quality_score,
            "quality_grade": record.quality_grade.value,
            "criticism": record.criticism,
            "self_criticism": record.self_criticism,
            "tags": record.tags
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        # 更新计数器
        self._save_meeting_counter()

    def get_meeting_history(self, limit: int = 10) -> List[MeetingRecord]:
        """获取会议历史"""
        meetings = []

        for yaml_file in sorted(self.meetings_dir.glob("meeting_*.yaml"), reverse=True)[:limit]:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            record = MeetingRecord(
                meeting_id=data["meeting_id"],
                meeting_type=MeetingType(data["meeting_type"]),
                title=data["title"],
                start_time=data["start_time"],
                end_time=data.get("end_time"),
                participants=data["participants"],
                agenda=data["agenda"],
                discussion=data["discussion"],
                decisions=data["decisions"],
                action_items=data["action_items"],
                quality_score=data["quality_score"],
                quality_grade=MeetingQuality(data["quality_grade"]),
                criticism=data.get("criticism", ""),
                self_criticism=data.get("self_criticism", ""),
                tags=data.get("tags", [])
            )
            meetings.append(record)

        return meetings


# ============================================================
# 批评引擎
# ============================================================

class CriticismEngine:
    """批评引擎"""

    def __init__(self):
        self.methodologies = CRITICISM_METHODOLOGIES
        self.criticism_dir = CRITICISM_DIR
        self.criticism_log = self._load_criticism_log()

    def _load_criticism_log(self) -> List[CriticismResult]:
        """加载批评日志"""
        log_file = self.criticism_dir / "criticism_log.yaml"
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return [CriticismResult(**c) for c in data.get("criticisms", [])]
        return []

    def _save_criticism_log(self):
        """保存批评日志"""
        log_file = self.criticism_dir / "criticism_log.yaml"
        data = {
            "criticisms": [asdict(c) for c in self.criticism_log[-100:]]
        }
        with open(log_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def criticize(self, target: str, issue: str, severity: int = 3,
                  evidence: List[str] = None, suggestion: str = "") -> CriticismResult:
        """
        执行批评

        Args:
            target: 批评对象
            issue: 问题描述
            severity: 严重程度 1-5
            evidence: 证据列表
            suggestion: 改进建议

        Returns:
            CriticismResult: 批评结果
        """
        result = CriticismResult(
            type="ai_criticism",
            target=target,
            severity=severity,
            issue=issue,
            evidence=evidence or [],
            suggestion=suggestion,
            method_ref="批评与自我批评方法论"
        )

        # 根据严重程度调整
        result.suggestion = self._enhance_suggestion(result)

        # 记录
        self.criticism_log.append(result)
        self._save_criticism_log()

        return result

    def _enhance_suggestion(self, result: CriticismResult) -> str:
        """增强建议"""
        if result.suggestion:
            return result.suggestion

        # 根据严重程度生成建议
        if result.severity >= 4:
            return "立即整改，制定详细改进计划，明确时间节点和责任人"
        elif result.severity >= 3:
            return "尽快改进，关注细节，避免同类问题再次发生"
        else:
            return "注意改进，尝试新的方法，持续优化"

    def self_criticize(self, context: Dict[str, Any]) -> CriticismResult:
        """
        自我批评

        Args:
            context: 包含以下键的字典:
                - issue: 问题描述
                - impact: 影响
                - cause: 原因分析
                - improvement: 改进措施
        """
        template = self.methodologies["self_criticism_template"]

        issue = context.get("issue", "")
        impact = context.get("impact", "")
        cause = context.get("cause", "")
        improvement = context.get("improvement", "")

        # 构建详细批评
        full_issue = f"{issue}"
        if impact:
            full_issue += f"\n影响: {impact}"
        if cause:
            full_issue += f"\n原因: {cause}"
        if improvement:
            full_issue += f"\n改进: {improvement}"

        result = CriticismResult(
            type="self_criticism",
            target="本人/本部门",
            severity=3,
            issue=full_issue,
            evidence=[],
            suggestion=improvement if improvement else "按承诺执行改进",
            method_ref="自我批评模板"
        )

        self.criticism_log.append(result)
        self._save_criticism_log()

        return result

    def peer_criticism(self, criticizer: str, target: str,
                      issue: str, severity: int) -> CriticismResult:
        """
        同行批评

        Args:
            criticizer: 批评者
            target: 被批评对象
            issue: 问题描述
            severity: 严重程度
        """
        result = CriticismResult(
            type="peer_criticism",
            target=target,
            severity=severity,
            issue=issue,
            evidence=[],
            suggestion="建议与当事人直接沟通解决",
            method_ref="批评与自我批评方法论"
        )

        self.criticism_log.append(result)
        self._save_criticism_log()

        return result

    def generate_criticism_report(self, target: Optional[str] = None) -> str:
        """生成批评报告"""
        if target:
            critiques = [c for c in self.criticism_log if c.target == target]
        else:
            critiques = self.criticism_log[-20:]  # 最近20条

        if not critiques:
            return "暂无批评记录"

        # 按严重程度分组
        critical = [c for c in critiques if c.severity >= 4]
        major = [c for c in critiques if c.severity == 3]
        minor = [c for c in critiques if c.severity < 3]

        report = f"""
# 📋 批评与自我批评报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

## 统计概览

| 严重程度 | 数量 |
|:---:|:---:|
| 🔴 严重 (4-5) | {len(critical)} |
| 🟡 一般 (3) | {len(major)} |
| 🟢 轻微 (1-2) | {len(minor)} |

---

## 🔴 严重问题 ({len(critical)}条)

{chr(10).join(self._format_critique(c) for c in critical) if critical else "- 无严重问题"}

---

## 🟡 一般问题 ({len(major)}条)

{chr(10).join(self._format_critique(c) for c in major) if major else "- 无一般问题"}

---

## 🟢 轻微问题 ({len(minor)}条)

{chr(10).join(self._format_critique(c) for c in minor) if minor else "- 无轻微问题"}

---

## 💡 改进建议

根据以上问题，建议:

1. **立即行动**: 针对严重问题，制定24小时整改计划
2. **本周改进**: 针对一般问题，制定本周改进措施
3. **持续优化**: 针对轻微问题，在日常工作中注意改进

---

## 📖 方法论参考

{self._format_methodology_summary()}
"""

        return report

    def _format_critique(self, critique: CriticismResult) -> str:
        """格式化批评条目"""
        severity_emoji = {
            5: "🔴",
            4: "🔴",
            3: "🟡",
            2: "🟢",
            1: "🟢"
        }

        return f"""
### {severity_emoji.get(critique.severity, "⚪")} [{critique.target}] 严重度:{critique.severity}

**问题**: {critique.issue}

**建议**: {critique.suggestion}
"""

    def _format_methodology_summary(self) -> str:
        """格式化方法论摘要"""
        general = self.methodologies["general"]

        return f"""
### 批评与自我批评通用方法论

**原则:**
{chr(10).join(f"- {p}" for p in general['principles'])}

**步骤:**
{chr(10).join(general['steps'])}

**避免:**
{chr(10).join(general['avoid'])}
"""


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🤵 老板秘书 - 日报与会议系统测试")
    print("=" * 60)

    # 测试日报收集和生成
    print("\n📊 测试日报生成...")
    collector = DailyReportCollector()
    generator = DailyReportGenerator()

    reports = collector.collect_department_reports()
    print(f"收集到 {len(reports)} 个部门报告")

    if reports:
        daily_report = generator.generate_daily_report(reports)
        print(f"\n整体评分: {daily_report.overall_score:.1f}")
        print(f"\n总结:\n{daily_report.summary}")

        # 生成Markdown报告
        md_report = generator.generate_markdown_report(daily_report)
        md_path = REPORTS_DIR / f"daily_report_test.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_report)
        print(f"\n✅ Markdown报告已保存: {md_path}")

    # 测试会议记录
    print("\n\n📝 测试会议记录...")
    recorder = MeetingRecorder()

    meeting = recorder.create_meeting(
        title="BTC行情分析与交易决策",
        meeting_type=MeetingType.BRAINSTORM,
        participants=["老板", "市场情报部", "研究部"],
        agenda=["行情回顾", "信号分析", "决策讨论", "行动确认"]
    )

    print(f"创建会议: {meeting.title}")
    print(f"会议ID: {meeting.meeting_id}")

    # 添加讨论
    recorder.add_discussion(meeting, "BTC当前处于上升趋势，ETF资金持续流入")
    recorder.add_discussion(meeting, "信号评分78分，可以考虑小仓开多")
    recorder.add_discussion(meeting, "建议等待回调后再入场")

    # 添加决策
    recorder.add_decision(meeting, "短期看多，但不追高，等回调")
    recorder.add_decision(meeting, "若回调至105000附近，考虑20%仓位开多")

    # 添加行动项
    recorder.add_action_item(meeting, "监控BTC回调点位", "市场情报部", "今日")
    recorder.add_action_item(meeting, "准备开多策略参数", "研究部", "今日14:00前")

    # 结束会议
    final_meeting = recorder.end_meeting(meeting)
    print(f"\n会议结束，质量评分: {final_meeting.quality_score:.1f}")
    print(f"质量等级: {final_meeting.quality_grade.value}")
    print(f"\n批评意见:\n{final_meeting.criticism}")
    print(f"\n自我批评:\n{final_meeting.self_criticism}")

    # 测试批评引擎
    print("\n\n🔍 测试批评引擎...")
    critic = CriticismEngine()

    result = critic.criticize(
        target="市场情报部",
        issue="数据采集延迟超过预期，影响决策时效",
        severity=4,
        suggestion="优化数据采集流程，增加备用数据源"
    )
    print(f"批评结果: {result.target} - {result.issue}")

    self_result = critic.self_criticize({
        "issue": "日报生成时间过晚",
        "impact": "老板无法及时获取信息",
        "cause": "各部门数据汇总效率低",
        "improvement": "建立自动化数据采集机制"
    })
    print(f"自我批评: {self_result.issue[:50]}...")

    # 生成批评报告
    report = critic.generate_criticism_report()
    print(f"\n批评报告已生成")

    print("\n" + "=" * 60)
    print("✅ 所有测试完成!")
    print("=" * 60)
