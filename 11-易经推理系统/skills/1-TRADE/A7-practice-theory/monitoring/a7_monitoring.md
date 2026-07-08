# A7 实践论应用监控机制

## 监控目标
确保A7实践论SKILL被正确应用到A4(战术验证)和A5(战术执行)中，并持续优化实践论应用效果。

## 监控指标

### 1. A7门禁检查触发率
```json
{
  "metric_name": "a7_gate_trigger_rate",
  "description": "A4/A5执行前A7门禁检查触发率",
  "calculation": "触发次数 / A4&A5总执行次数",
  "target": ">95%",
  "measurement": "每日统计"
}
```

### 2. A7门禁检查通过率
```json
{
  "metric_name": "a7_gate_pass_rate",
  "description": "A7门禁检查通过率",
  "calculation": "通过次数 / 总检查次数",
  "target": ">80% (初期可放宽至>60%)",
  "measurement": "每日统计"
}
```

### 3. 实践日志记录完整率
```json
{
  "metric_name": "practice_log_completeness",
  "description": "A4/A5执行后实践日志记录完整率",
  "calculation": "完整日志数 / A4&A5总执行次数",
  "target": ">90%",
  "measurement": "每日统计"
}
```

### 4. 认识修正频率
```json
{
  "metric_name": "recognition_correction_frequency",
  "description": "根据A4反馈修正A1-A3认识的频率",
  "calculation": "认识修正次数 / A4验证次数",
  "target": ">30% (认识需要不断修正)",
  "measurement": "每周统计"
}
```

### 5. 实践→认识→实践循环完成率
```json
{
  "metric_name": "practice_cycle_completion_rate",
  "description": "完整实践循环完成率",
  "calculation": "完成循环数 / 启动循环数",
  "target": ">70%",
  "measurement": "每周统计"
}
```

## 监控实施

### 每日监控 (自动)
```python
# 监控脚本: a7_daily_monitor.py
def daily_monitoring():
    """每日监控A7应用情况"""
    
    # 1. 统计A4/A5执行次数
    a4_count = count_a4_executions_today()
    a5_count = count_a5_executions_today()
    
    # 2. 统计A7门禁检查触发次数
    a7_trigger_count = count_a7_gate_triggers_today()
    trigger_rate = (a7_trigger_count / (a4_count + a5_count)) * 100
    
    # 3. 统计A7门禁检查通过次数
    a7_pass_count = count_a7_gate_passes_today()
    pass_rate = (a7_pass_count / a7_trigger_count) * 100 if a7_trigger_count > 0 else 0
    
    # 4. 统计实践日志记录完整率
    practice_log_count = count_practice_logs_today()
    log_completeness = (practice_log_count / (a4_count + a5_count)) * 100
    
    # 5. 生成监控报告
    report = {
        "date": today(),
        "a4_executions": a4_count,
        "a5_executions": a5_count,
        "a7_triggers": a7_trigger_count,
        "trigger_rate": f"{trigger_rate:.1f}%",
        "a7_passes": a7_pass_count,
        "pass_rate": f"{pass_rate:.1f}%",
        "practice_logs": practice_log_count,
        "log_completeness": f"{log_completeness:.1f}%",
        "alerts": []
    }
    
    # 6. 触发告警
    if trigger_rate < 95:
        report["alerts"].append("⚠️ A7门禁检查触发率过低")
    
    if pass_rate < 60:
        report["alerts"].append("⚠️ A7门禁检查通过率过低")
    
    if log_completeness < 90:
        report["alerts"].append("⚠️ 实践日志记录完整率过低")
    
    # 7. 保存报告
    save_daily_monitoring_report(report)
    
    return report
```

### 每周监控 (自动)
```python
# 监控脚本: a7_weekly_monitor.py
def weekly_monitoring():
    """每周监控A7应用效果"""
    
    # 1. 统计认识修正频率
    recognition_corrections = count_recognition_corrections_this_week()
    a4_validations = count_a4_validations_this_week()
    correction_frequency = (recognition_corrections / a4_validations) * 100 if a4_validations > 0 else 0
    
    # 2. 统计实践循环完成率
    completed_cycles = count_completed_practice_cycles_this_week()
    started_cycles = count_started_practice_cycles_this_week()
    completion_rate = (completed_cycles / started_cycles) * 100 if started_cycles > 0 else 0
    
    # 3. 分析A7门禁检查失败原因
    failure_reasons = analyze_a7_gate_failures_this_week()
    
    # 4. 生成每周监控报告
    report = {
        "week": get_week_number(),
        "recognition_corrections": recognition_corrections,
        "a4_validations": a4_validations,
        "correction_frequency": f"{correction_frequency:.1f}%",
        "completed_cycles": completed_cycles,
        "started_cycles": started_cycles,
        "completion_rate": f"{completion_rate:.1f}%",
        "failure_reasons": failure_reasons,
        "recommendations": []
    }
    
    # 5. 生成改进建议
    if correction_frequency < 30:
        report["recommendations"].append("认识修正频率过低，需要加强A4反馈机制")
    
    if completion_rate < 70:
        report["recommendations"].append("实践循环完成率过低，需要优化实践流程")
    
    # 6. 保存报告
    save_weekly_monitoring_report(report)
    
    return report
```

## 监控报告模板

### 每日监控报告
```markdown
# A7 实践论应用监控日报 - {YYYY-MM-DD}

## 核心指标
| 指标 | 数值 | 目标 | 状态 |
|:---|:---:|:---:|:---:|
| A4执行次数 | {a4_count} | - | - |
| A5执行次数 | {a5_count} | - | - |
| A7门禁检查触发次数 | {a7_triggers} | - | - |
| A7门禁检查触发率 | {trigger_rate} | >95% | {status} |
| A7门禁检查通过次数 | {a7_passes} | - | - |
| A7门禁检查通过率 | {pass_rate} | >80% | {status} |
| 实践日志记录数 | {practice_logs} | - | - |
| 实践日志记录完整率 | {log_completeness} | >90% | {status} |

## 告警
{alerts}

## 建议
{suggestions}

---
*报告生成时间: {timestamp}*
```

### 每周监控报告
```markdown
# A7 实践论应用监控周报 - 第{week}周

## 核心指标
| 指标 | 数值 | 目标 | 状态 |
|:---|:---:|:---:|:---:|
| 认识修正次数 | {recognition_corrections} | - | - |
| A4验证次数 | {a4_validations} | - | - |
| 认识修正频率 | {correction_frequency} | >30% | {status} |
| 完成实践循环数 | {completed_cycles} | - | - |
| 启动实践循环数 | {started_cycles} | - | - |
| 实践循环完成率 | {completion_rate} | >70% | {status} |

## A7门禁检查失败原因分析
{failure_reasons}

## 改进建议
{recommendations}

## 下周重点
{next_week_focus}

---
*报告生成时间: {timestamp}*
```

## 监控实施时间表

| 监控类型 | 执行频率 | 执行时间 | 输出 |
|:---|:---:|:---|:---|
| 每日监控 | 每天 | 23:59 | 日报 |
| 每周监控 | 每周 | 周日 23:59 | 周报 |
| 每月回顾 | 每月 | 月末 | 月报 |

## 监控自动化

### 创建自动化任务
```bash
# 每日监控自动化
0 23 * * * cd /Users/zhangjiangtao/.workbuddy/skills/A7-practice-theory/monitoring && python3 a7_daily_monitor.py

# 每周监控自动化
0 23 * * 0 cd /Users/zhangjiangtao/.workbuddy/skills/A7-practice-theory/monitoring && python3 a7_weekly_monitor.py
```

---

*创建时间: 2026-04-26*
*创建者: A7实践论SKILL Phase 4上线运行*