#!/usr/bin/env python3
"""
产物同步脚本 v5.3 - 将自动化任务生成的文档同步到前端产物中心

功能：
1. 按文件名模式自动分类到 ~/.workbudbuddy/artifacts/ 对应目录
2. 支持手动指定分类覆盖
3. 自动提取 A0-A9 阶段
4. 更新对应目录的 index.json（自动按时间降序排序）
5. 支持8大部门：交易部、做梦部、治理部、知识库、支撑部、调研部、人力资源部、秘书部
6. 时间戳严格验证（P0/P1/P2违规等级）

v5.3 更新：
- 修复新产物未排在首位的排序问题
- 保存 index.json 前自动按时间戳降序排序（最新在前）

使用方法：
  python3 sync_artifact.py --source <源文件> [--category <分类>]

  自动模式（默认）: 按文件名匹配规则自动分类
  手动模式: --category <分类> 覆盖自动匹配

时间戳规范 (v5.3 - AAM SKILL v7.3):
  标准格式: YYYY-MM-DDTHH:MM:SS+08:00
  纯日期格式: YYYY-MM-DD
  紧凑格式: YYYYMMDD_HHMMSS

  ⚠️ P0 致命违规: frontmatter date 缺失/格式错误 → 禁止投递
  ⚠️ P1 警告: index.json 与 frontmatter 不一致
  ⚠️ P2 建议: 文件名时间戳格式不统一

分类映射规则 (v5.0):
  a_series       → 📊 交易部 - A0-A9交易产物
  oneirology     → 🌙 做梦部 - 做梦日志与分析
  governance     → ⚖️ 治理部 - 宪法、FAQ、工程索引
  knowledge      → 📚 知识库 - 策略、工具、经验沉淀
  audit          → 🔧 支撑部 - 审计、运营、健康监控
  research       → 🔬 调研部 - 深度调研、情报分析
  hr             → 👥 人力资源部 - 绩效、技能、招聘
  secretary      → 🏛️ 秘书部 - 临时文件、跨部门协调（默认）
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============================================================
# 腾讯云远程同步配置 (v5.4 - 自动同步index.json)
# ============================================================
# 远程服务器配置
TENCENT_CLOUD_ENABLED = True  # 是否启用腾讯云同步
TENCENT_CLOUD_SERVER = "49.233.123.96"
TENCENT_CLOUD_USER = "ubuntu"
TENCENT_CLOUD_KEY = os.path.expanduser("~/Desktop/yunya.pem")
TENCENT_CLOUD_REMOTE_ROOT = "/home/ubuntu/.workbuddy/artifacts"

def sync_to_tencent_cloud(local_file: str, category: str, verbose: bool = True) -> bool:
    """
    同步文件到腾讯云远程服务器
    
    Args:
        local_file: 本地文件路径
        category: 分类目录名（trading/oneirology/governance等）
        verbose: 是否输出详细信息
    
    Returns:
        bool: 是否成功
    """
    if not TENCENT_CLOUD_ENABLED:
        return True
    
    if not os.path.exists(TENCENT_CLOUD_KEY):
        print(f"⚠️ SSH密钥不存在: {TENCENT_CLOUD_KEY}")
        return False
    
    # 构建远程路径
    remote_path = f"{TENCENT_CLOUD_USER}@{TENCENT_CLOUD_SERVER}:{TENCENT_CLOUD_REMOTE_ROOT}/{category}/"
    
    # 构建rsync命令
    rsync_cmd = [
        'rsync', '-avz', '--progress',
        '-e', f'ssh -i {TENCENT_CLOUD_KEY} -o StrictHostKeyChecking=no',
        local_file,
        remote_path
    ]
    
    try:
        if verbose:
            print(f"☁️  同步到腾讯云: {os.path.basename(local_file)} → {remote_path}")
        
        result = subprocess.run(
            rsync_cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        if verbose:
            print(f"✅ 腾讯云同步成功")
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️ 腾讯云同步失败: {e.stderr}")
        return False
    except Exception as e:
        print(f"⚠️ 腾讯云同步异常: {e}")
        return False
# ============================================================
# 时间戳规范化工具（v2.0 - 统一收口）
# ============================================================
# 北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))

def normalize_timestamp(ts_input=None, output_format="iso"):
    """
    统一时间戳生成器 - AAM SKILL 规范收口
    
    Args:
        ts_input: 时间输入（str/datetime/None），None=当前时间
        output_format: 
            - "iso": YYYY-MM-DDTHH:MM:SS+08:00（标准格式，带时区）
            - "date_only": YYYY-MM-DD（纯日期）
            - "compact": YYYYMMDD_HHMMSS（文件名用）
    
    Returns:
        str: 规范化后的时间戳字符串
    """
    # 解析输入时间
    if ts_input is None:
        dt = datetime.now(BEIJING_TZ)
    elif isinstance(ts_input, str):
        # 尝试解析各种格式
        ts_input = ts_input.strip()
        
        # 纯日期格式 YYYY-MM-DD
        if re.match(r'^\d{4}-\d{2}-\d{2}$', ts_input):
            dt = datetime.strptime(ts_input, '%Y-%m-%d').replace(tzinfo=BEIJING_TZ)
        # 带时间的标准格式
        elif 'T' in ts_input or '+' in ts_input or ts_input.endswith('Z'):
            # 移除末尾Z并添加时区
            clean_ts = ts_input.replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(clean_ts)
                # 如果没有时区信息，假设是北京时间
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=BEIJING_TZ)
            except:
                dt = datetime.now(BEIJING_TZ)
        # 简单日期时间格式 YYYY-MM-DD HH:MM:SS
        elif re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}$', ts_input):
            ts_input = ts_input.replace(' ', 'T')
            dt = datetime.strptime(ts_input, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=BEIJING_TZ)
        else:
            dt = datetime.now(BEIJING_TZ)
    elif isinstance(ts_input, datetime):
        dt = ts_input
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BEIJING_TZ)
    else:
        dt = datetime.now(BEIJING_TZ)
    
    # 输出指定格式
    if output_format == "iso":
        return dt.strftime('%Y-%m-%dT%H:%M:%S+08:00')
    elif output_format == "date_only":
        return dt.strftime('%Y-%m-%d')
    elif output_format == "compact":
        return dt.strftime('%Y%m%d_%H%M%S')
    else:
        return dt.strftime('%Y-%m-%dT%H:%M:%S+08:00')


def validate_timestamp_format(ts_str):
    """
    验证时间戳是否符合 AAM 规范
    
    Returns:
        tuple: (is_valid, normalized, error_message)
    """
    if not ts_str:
        return False, None, "空时间戳"
    
    # 检查标准格式
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$', ts_str):
        return True, ts_str, None
    
    # 检查纯日期格式
    if re.match(r'^\d{4}-\d{2}-\d{2}$', ts_str):
        return True, ts_str, None
    
    # 其他格式需要规范化
    normalized = normalize_timestamp(ts_str)
    return True, normalized, f"已自动规范化为 {normalized}"


# 配置
HOME = os.path.expanduser("~")
ARTIFACTS_ROOT = os.path.join(HOME, ".workbuddy/artifacts")

# A0-A9 阶段正则
A_PHASE_PATTERN = re.compile(r'^A([0-9])$', re.IGNORECASE)

# 文件名模式 → 分类映射 (v5.4 - 修正A系列分类)
FILENAME_PATTERN_MAP = [
    # 📊 交易部 - A系列主干（根据artifact-alignment-manager SKILL 6.3节）
    (re.compile(r'^(a[0-9])_', re.IGNORECASE), 'trading'),
    (re.compile(r'^A([0-9])_', re.IGNORECASE), 'trading'),
    (re.compile(r'^episode_', re.IGNORECASE), 'trading'),
    # A9 exit_check 归类为 trading（交易部）
    (re.compile(r'^exit_check_', re.IGNORECASE), 'trading'),
    (re.compile(r'^a9_exit_', re.IGNORECASE), 'trading'),
    # A6情报简报归类为trading（交易部）- 必须在research_之前匹配
    (re.compile(r'^a6_intelligence', re.IGNORECASE), 'trading'),
    
    # 🌙 做梦部
    (re.compile(r'^dream_journal_', re.IGNORECASE), 'oneirology'),
    (re.compile(r'^oneirology_', re.IGNORECASE), 'oneirology'),
    (re.compile(r'^dream_insight_', re.IGNORECASE), 'oneirology'),
    (re.compile(r'^dream_gate_audit_', re.IGNORECASE), 'oneirology'),   # 做梦部门禁审计
    (re.compile(r'^dream_research_agenda_', re.IGNORECASE), 'oneirology'),  # 做梦部研究议程
    (re.compile(r'^dream_brainstorm_', re.IGNORECASE), 'oneirology'),   # 做梦部头脑风暴
    
    # ⚖️ 治理部
    (re.compile(r'^governance_', re.IGNORECASE), 'governance'),
    (re.compile(r'^constitution_', re.IGNORECASE), 'governance'),
    (re.compile(r'^faq_', re.IGNORECASE), 'governance'),
    (re.compile(r'^engineering_index_', re.IGNORECASE), 'governance'),
    (re.compile(r'^organization_', re.IGNORECASE), 'governance'),
    (re.compile(r'^charter_', re.IGNORECASE), 'governance'),
    (re.compile(r'^violation_', re.IGNORECASE), 'governance'),
    (re.compile(r'^policy_', re.IGNORECASE), 'governance'),
    
    # 🔧 支撑部
    (re.compile(r'^audit_', re.IGNORECASE), 'audit'),
    (re.compile(r'^gate_audit_', re.IGNORECASE), 'audit'),
    (re.compile(r'^ops_health_', re.IGNORECASE), 'audit'),
    (re.compile(r'^operation_health_', re.IGNORECASE), 'audit'),
    
    # 🔬 调研部
    (re.compile(r'^research_', re.IGNORECASE), 'research'),
    (re.compile(r'^deep_research_', re.IGNORECASE), 'research'),
    (re.compile(r'^intelligence_', re.IGNORECASE), 'research'),
    
    # 👥 人力资源部
    (re.compile(r'^hr_', re.IGNORECASE), 'hr'),
    (re.compile(r'^performance_review_', re.IGNORECASE), 'hr'),
    (re.compile(r'^capability_', re.IGNORECASE), 'hr'),
    
    # 📚 知识库
    (re.compile(r'^knowledge_', re.IGNORECASE), 'knowledge'),
    (re.compile(r'^masters_', re.IGNORECASE), 'knowledge'),
    (re.compile(r'^distillation_', re.IGNORECASE), 'knowledge'),
    (re.compile(r'^lessons_', re.IGNORECASE), 'knowledge'),
    (re.compile(r'^strategy_', re.IGNORECASE), 'trading'),
    (re.compile(r'^okx_', re.IGNORECASE), 'knowledge'),
    (re.compile(r'^macro_', re.IGNORECASE), 'knowledge'),
    (re.compile(r'^risk_', re.IGNORECASE), 'risk'),
    # exit_ 放在后面（exit_check_已匹配）
    (re.compile(r'^exit_', re.IGNORECASE), 'exit'),
    (re.compile(r'^practice_', re.IGNORECASE), 'practice'),
    (re.compile(r'^web_strategy_', re.IGNORECASE), 'web_strategy'),
    (re.compile(r'^advanced_order_', re.IGNORECASE), 'advanced_orders'),
    (re.compile(r'^tools_', re.IGNORECASE), 'tools'),
    (re.compile(r'^cost_', re.IGNORECASE), 'audit'),
    (re.compile(r'^efficiency_', re.IGNORECASE), 'audit'),
    (re.compile(r'^market_intel_', re.IGNORECASE), 'a_series'),
    (re.compile(r'^proposal_', re.IGNORECASE), 'governance'),
    (re.compile(r'^postmortem_', re.IGNORECASE), 'audit'),
    (re.compile(r'^seminar_', re.IGNORECASE), 'a_series'),
]

# 分类 → 部门映射 (v5.0)
CATEGORY_DEPARTMENT_MAP = {
    'a_series': 'trading',
    'trading': 'trading',
    'oneirology': 'oneirology',
    'governance': 'governance',
    'knowledge': 'knowledge',
    'audit': 'audit',
    'research': 'research',
    'hr': 'hr',
    'secretary': 'secretary',
}

# 有效分类列表
VALID_CATEGORIES = list(CATEGORY_DEPARTMENT_MAP.keys())


def extract_a_phase(filename: str) -> str:
    """从文件名中提取 A0-A9 阶段"""
    match = re.search(r'A([0-9])', filename, re.IGNORECASE)
    if match:
        return f"A{match.group(1)}"
    return ""


def match_category(filename: str) -> str:
    """根据文件名模式匹配分类"""
    for pattern, category in FILENAME_PATTERN_MAP:
        if pattern.search(filename):
            return category
    # 默认归入 secretary（秘书部）
    return 'secretary'


def ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def load_index(category_dir: str) -> list:
    """加载分类目录的 index.json"""
    index_file = os.path.join(category_dir, "index.json")
    if os.path.exists(index_file):
        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else data.get('artifacts', [])
        except:
            return []
    return []


def save_index(category_dir: str, artifacts: list, verbose: bool = True):
    """保存 index.json 并自动同步到腾讯云"""
    index_file = os.path.join(category_dir, "index.json")
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(artifacts, f, ensure_ascii=False, indent=2)
    
    # 提取分类名（从路径中）
    category = os.path.basename(category_dir)
    
    # 自动同步到腾讯云
    if TENCENT_CLOUD_ENABLED:
        sync_to_tencent_cloud(index_file, category, verbose)


def get_file_metadata(filepath: str) -> dict:
    """获取文件元数据（从 markdown frontmatter 或文件名）"""
    metadata = {
        'title': '',
        'date': normalize_timestamp(output_format="iso"),  # 统一使用规范时间戳
        'status': 'completed',
        'type': 'knowledge',
        'tags': [],
        'chain_phase': ''
    }
    
    # 如果是JSON文件，尝试从JSON中提取元数据
    if filepath.endswith('.json'):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 从JSON中提取元数据
                for key in ['title', 'date', 'status', 'type', 'tags', 'chain_phase']:
                    if key in data and key in metadata:
                        if key == 'date':
                            # 规范化时间戳
                            is_valid, normalized, _ = validate_timestamp_format(data[key])
                            metadata[key] = normalized if normalized else metadata['date']
                        elif key == 'tags' and isinstance(data[key], list):
                            metadata[key] = data[key]
                        else:
                            metadata[key] = data[key]
                return metadata  # JSON文件的元数据已提取完毕，直接返回
        except Exception as e:
            print(f"⚠️ 无法解析JSON: {e}")
            # 继续尝试markdown frontmatter（虽然对.json文件不太可能）
    
    # 尝试从 markdown frontmatter 读取
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if content.startswith('---'):
                end_idx = content.find('---', 3)
                if end_idx > 0:
                    fm_text = content[3:end_idx]
                    # 简单解析 yaml-like frontmatter
                    for line in fm_text.split('\n'):
                        if ':' in line:
                            key, _, value = line.partition(':')
                            key = key.strip()
                            value = value.strip().strip('"\'')
                            if key in metadata:
                                # 处理特殊类型
                                if key == 'tags':
                                    metadata[key] = [v.strip() for v in value.split(',')]
                                elif key == 'date':
                                    # 规范化时间戳
                                    is_valid, normalized, _ = validate_timestamp_format(value)
                                    metadata[key] = normalized if normalized else metadata['date']
                                else:
                                    metadata[key] = value
    except Exception as e:
        print(f"⚠️ 无法读取 frontmatter: {e}")
    
    # 从文件名提取 A 阶段
    filename = os.path.basename(filepath)
    if not metadata.get('chain_phase'):
        metadata['chain_phase'] = extract_a_phase(filename)
    
    # 从文件名生成标题
    if not metadata.get('title'):
        # 移除扩展名和日期后缀
        name = os.path.splitext(filename)[0]
        name = re.sub(r'_\d{8}(_\d{4})?$', '', name)
        metadata['title'] = name.replace('_', ' ').title()
    
    return metadata


def sync_artifact(source_path: str, category: str = None, a_phase: str = None, verbose: bool = True) -> bool:
    """
    同步单个产物到前端
    
    Args:
        source_path: 源文件路径
        category: 分类（可选，自动匹配如果不指定）
        a_phase: 指定的 A 阶段（可选，自动提取如果未指定）
        verbose: 是否输出详细信息
    
    Returns:
        bool: 是否成功
    """
    if not os.path.exists(source_path):
        print(f"❌ 源文件不存在: {source_path}")
        return False
    
    # 获取文件名
    filename = os.path.basename(source_path)
    
    # 自动匹配分类
    if not category:
        category = match_category(filename)
        if verbose:
            print(f"📋 自动匹配分类: {filename} → {category}")
    
    # 验证分类有效性
    if category not in VALID_CATEGORIES:
        print(f"⚠️ 无效分类 '{category}'，使用 'knowledge'")
        category = 'knowledge'
    
    # 确保目标目录存在
    category_dir = os.path.join(ARTIFACTS_ROOT, category)
    ensure_dir(category_dir)
    
    # 复制文件到目标目录
    target_path = os.path.join(category_dir, filename)
    shutil.copy2(source_path, target_path)
    if verbose:
        print(f"✅ 已复制: {filename} → {category}/")
    
    # 获取元数据
    metadata = get_file_metadata(source_path)
    
    # 如果指定了 A 阶段，覆盖自动提取的值
    if a_phase and A_PHASE_PATTERN.match(a_phase.upper()):
        metadata['chain_phase'] = a_phase.upper()
        if verbose:
            print(f"📌 指定 A 阶段: {a_phase.upper()}")
    elif metadata.get('chain_phase'):
        if verbose:
            print(f"📌 自动识别 A 阶段: {metadata['chain_phase']}")
    
    # 生成 artifact_id（不含扩展名）
    artifact_id = os.path.splitext(filename)[0]
    
    # 加载现有索引
    artifacts = load_index(category_dir)
    
    # 检查是否已存在
    existing_idx = None
    for i, a in enumerate(artifacts):
        if a.get('id') == f"{category}/{artifact_id}":
            existing_idx = i
            break
    
    # 构建索引条目
    entry = {
        "id": f"{category}/{artifact_id}",
        "file": filename,
        "title": metadata.get('title', artifact_id),
        "department": CATEGORY_DEPARTMENT_MAP.get(category, 'knowledge'),
        "type": metadata.get('type', 'knowledge'),
        "date": metadata.get('date', datetime.now().strftime('%Y-%m-%d')),
        "status": metadata.get('status', 'completed'),
        "chain_phase": metadata.get('chain_phase', ''),
        "url": f"/feed/{category}/{artifact_id}",
        "tags": ' '.join(metadata.get('tags', [])) if isinstance(metadata.get('tags'), list) else ''
    }
    
    if existing_idx is not None:
        # 更新现有条目
        artifacts[existing_idx] = entry
        if verbose:
            print(f"✅ 已更新索引: {artifact_id}")
    else:
        # 添加新条目
        artifacts.append(entry)
        if verbose:
            print(f"✅ 已添加索引: {artifact_id}")
    
    # 保存索引前按时间戳降序排序（最新的在最前）
    # 使用 ISO 格式时间戳进行排序
    def sort_key(item):
        date_str = item.get('date', '')
        # 纯日期格式补全为 00:00:00+08:00 以便排序
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str + 'T00:00:00+08:00'
        return date_str
    
    artifacts.sort(key=sort_key, reverse=True)
    save_index(category_dir, artifacts)
    
    return True


def sync_mailbox(mailbox_dir: str, verbose: bool = True, hours: int = 0) -> dict:
    """
    扫描邮箱目录，同步所有文件到前端

    Args:
        mailbox_dir: 邮箱目录路径
        verbose: 是否输出详细信息
        hours: 只同步最近N小时内的文件，0=全部同步（⚠️不推荐，会污染前端）

    Returns:
        dict: 同步统计
    """
    stats = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'categories': {}
    }

    if not os.path.exists(mailbox_dir):
        if verbose:
            print(f"⚠️ 目录不存在: {mailbox_dir}")
        return stats

    # 计算时间阈值
    cutoff_time = 0
    if hours > 0:
        cutoff_time = time.time() - hours * 3600
        if verbose:
            print(f"⏰ 增量模式: 只同步最近 {hours} 小时内的文件")

    # 递归扫描所有子目录中的 .md 文件
    for root, dirs, files in os.walk(mailbox_dir):
        for filename in files:
            if not filename.endswith('.md'):
                continue

            filepath = os.path.join(root, filename)
            if not os.path.isfile(filepath):
                continue

            # 增量模式：检查文件修改时间
            if hours > 0:
                file_mtime = os.path.getmtime(filepath)
                if file_mtime < cutoff_time:
                    stats['skipped'] += 1
                    continue

            stats['total'] += 1

            # 同步文件
            try:
                if sync_artifact(filepath, verbose=verbose):
                    stats['success'] += 1
                    # 统计分类
                    category = match_category(filename)
                    stats['categories'][category] = stats['categories'].get(category, 0) + 1
                else:
                    stats['failed'] += 1
            except Exception as e:
                if verbose:
                    print(f"❌ 同步失败 {filename}: {e}")
                stats['failed'] += 1

    if verbose and stats['skipped'] > 0:
        print(f"⏭️ 跳过旧文件: {stats['skipped']}")

    return stats


def verify_mailbox_sync(mailbox_dir: str, verbose: bool = True) -> dict:
    """
    验证邮箱目录与前端产物中心的同步状态

    Args:
        mailbox_dir: 邮箱目录路径
        verbose: 是否输出详细信息

    Returns:
        dict: 验证结果
    """
    result = {
        'mailbox_files': set(),
        'frontend_files': set(),
        'missing_in_frontend': [],
        'extra_in_frontend': [],
        'sync_rate': 0.0
    }

    if not os.path.exists(mailbox_dir):
        if verbose:
            print(f"⚠️ 目录不存在: {mailbox_dir}")
        return result

    # 扫描邮箱目录中的 .md 文件
    for filename in os.listdir(mailbox_dir):
        if filename.endswith('.md'):
            result['mailbox_files'].add(filename)

    # 扫描前端产物目录
    for category in os.listdir(ARTIFACTS_ROOT):
        category_dir = os.path.join(ARTIFACTS_ROOT, category)
        if not os.path.isdir(category_dir):
            continue

        for filename in os.listdir(category_dir):
            if filename.endswith('.md'):
                result['frontend_files'].add(filename)

    # 计算差异
    result['missing_in_frontend'] = list(result['mailbox_files'] - result['frontend_files'])
    result['extra_in_frontend'] = list(result['frontend_files'] - result['mailbox_files'])

    # 计算同步率
    if result['mailbox_files']:
        matched = len(result['mailbox_files']) - len(result['missing_in_frontend'])
        result['sync_rate'] = matched / len(result['mailbox_files']) * 100

    if verbose:
        print(f"\n📊 同步验证结果:")
        print(f"   邮箱文件数: {len(result['mailbox_files'])}")
        print(f"   前端文件数: {len(result['frontend_files'])}")
        print(f"   同步率: {result['sync_rate']:.1f}%")
        print(f"   漏同步: {len(result['missing_in_frontend'])}")
        print(f"   多同步: {len(result['extra_in_frontend'])}")

    return result


# ============================================================
# 时间戳严格验证（v5.2 - AAM SKILL v7.2）
# ============================================================

def validate_timestamp_strict(ts_str: str) -> tuple:
    """
    严格验证时间戳，返回违规等级

    Returns:
        tuple: (level, normalized, message)
            level: "P0" (致命), "P1" (警告), "P2" (建议), "OK" (合规)
    """
    if not ts_str:
        return "P0", None, "时间戳为空"

    # 检查标准格式（完全合规）
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}$', ts_str):
        # 检查补零
        if re.search(r'-\d-\dT', ts_str):
            return "P2", ts_str, "月/日缺少补零"
        return "OK", ts_str, None

    # 检查纯日期格式
    if re.match(r'^\d{4}-\d{2}-\d{2}$', ts_str):
        normalized = normalize_timestamp(ts_str, output_format="iso")
        return "P1", normalized, f"纯日期已规范化为 {normalized}"

    # 其他格式：尝试规范化
    normalized = normalize_timestamp(ts_str)
    if normalized:
        return "P1", normalized, f"已自动规范化为 {normalized}"

    return "P0", None, "无法解析时间戳"


def validate_file_timestamp(filepath: str, verbose: bool = True) -> dict:
    """
    验证单个文件的 frontmatter 时间戳

    Returns:
        dict: 验证结果 {file, level, date, normalized, message}
    """
    result = {
        'file': filepath,
        'level': 'OK',
        'date': None,
        'normalized': None,
        'message': None
    }

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取 frontmatter
        if not content.startswith('---'):
            if verbose:
                print(f"🔴 {filepath}: 缺少 frontmatter")
            result['level'] = "P0"
            result['message'] = "缺少 frontmatter"
            return result

        end_idx = content.find('---', 3)
        if end_idx < 0:
            result['level'] = "P0"
            result['message'] = "frontmatter 未闭合"
            return result

        fm_text = content[3:end_idx]
        date_found = False

        for line in fm_text.split('\n'):
            line = line.strip()
            if line.startswith('date:'):
                date_found = True
                ts_value = line.split(':', 1)[1].strip().strip('"\'')
                result['date'] = ts_value

                level, normalized, msg = validate_timestamp_strict(ts_value)
                result['level'] = level
                result['normalized'] = normalized
                result['message'] = msg

                if verbose:
                    if level == "P0":
                        print(f"🔴 {filepath}: {msg}")
                    elif level == "P1":
                        print(f"🟡 {filepath}: {msg}")
                    elif level == "P2":
                        print(f"🟢 {filepath}: {msg} (建议修复)")
                return result

        if not date_found:
            result['level'] = "P0"
            result['message'] = "缺少 date 字段"
            if verbose:
                print(f"🔴 {filepath}: 缺少 date 字段")

    except Exception as e:
        result['level'] = "P0"
        result['message'] = f"读取失败: {e}"
        if verbose:
            print(f"🔴 {filepath}: {e}")

    return result


def validate_all_artifacts(artifacts_dir: str = None, verbose: bool = True) -> dict:
    """
    批量验证所有产物的时间戳

    Returns:
        dict: {P0: [], P1: [], P2: [], OK: [], total}
    """
    if artifacts_dir is None:
        artifacts_dir = ARTIFACTS_ROOT

    stats = {'P0': [], 'P1': [], 'P2': [], 'OK': [], 'total': 0}

    if not os.path.exists(artifacts_dir):
        if verbose:
            print(f"❌ 目录不存在: {artifacts_dir}")
        return stats

    # 遍历所有 .md 文件
    for root, dirs, files in os.walk(artifacts_dir):
        for filename in files:
            if not filename.endswith('.md'):
                continue

            filepath = os.path.join(root, filename)
            result = validate_file_timestamp(filepath, verbose=False)
            stats['total'] += 1

            if result['level'] == 'P0':
                stats['P0'].append(result)
            elif result['level'] == 'P1':
                stats['P1'].append(result)
            elif result['level'] == 'P2':
                stats['P2'].append(result)
            else:
                stats['OK'].append(result)

    if verbose:
        print(f"\n📊 时间戳批量验证结果:")
        print(f"   总文件: {stats['total']}")
        print(f"   🔴 P0 致命: {len(stats['P0'])}")
        print(f"   🟡 P1 警告: {len(stats['P1'])}")
        print(f"   🟢 P2 建议: {len(stats['P2'])}")
        print(f"   ✅ 合规: {len(stats['OK'])}")

        if stats['P0']:
            print(f"\n🔴 P0 致命违规 (禁止投递):")
            for r in stats['P0'][:10]:
                print(f"   - {r['file']}: {r['message']}")

        if stats['P1']:
            print(f"\n🟡 P1 警告 (需修复后重新 sync):")
            for r in stats['P1'][:10]:
                print(f"   - {r['file']}: {r['date']} → {r['normalized']}")

    return stats


def validate_index_json(index_path: str, verbose: bool = True) -> dict:
    """
    验证 index.json 中的时间戳

    Returns:
        dict: {P0: [], P1: [], OK: [], total}
    """
    stats = {'P0': [], 'P1': [], 'OK': [], 'total': 0}

    if not os.path.exists(index_path):
        if verbose:
            print(f"❌ 文件不存在: {index_path}")
        return stats

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for item in data:
            stats['total'] += 1
            date_str = item.get('date', '')
            title = item.get('title', item.get('id', ''))

            level, normalized, msg = validate_timestamp_strict(date_str)

            result = {
                'file': index_path,
                'title': title,
                'date': date_str,
                'normalized': normalized,
                'message': msg
            }

            if level == 'P0':
                stats['P0'].append(result)
                if verbose:
                    print(f"🔴 [{title}]: {msg}")
            elif level == 'P1':
                stats['P1'].append(result)
                if verbose:
                    print(f"🟡 [{title}]: {msg}")
            else:
                stats['OK'].append(result)

        if verbose:
            print(f"\n📊 index.json 时间戳验证结果:")
            print(f"   总条目: {stats['total']}")
            print(f"   🔴 P0: {len(stats['P0'])}")
            print(f"   🟡 P1: {len(stats['P1'])}")
            print(f"   ✅ 合规: {len(stats['OK'])}")

    except Exception as e:
        if verbose:
            print(f"❌ 解析失败: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='产物同步脚本 v5.2 - 文档流转前端产物中心（8大部门） + 时间戳规范化',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
时间戳规范化 (v2.0 - AAM SKILL v7.2 严格规范):
  # 验证单个时间戳（返回 P0/P1 违规检查结果）
  python3 sync_artifact.py --check-ts "2026-05-06T10:00:00+08:00"
  python3 sync_artifact.py --check-ts "2026-05-06"  # 纯日期

  # 批量验证所有产物时间戳（返回违规列表）
  python3 sync_artifact.py --validate-all ~/.workbuddy/artifacts/

  # 批量规范化前端的 index.json
  python3 sync_artifact.py --normalize-index ~/.workbuddy/artifacts/trading/index.json

  # 验证 index.json（返回 P0 违规）
  python3 sync_artifact.py --validate-index ~/.workbuddy/artifacts/trading/index.json

示例:
  # 自动模式（按文件名匹配）- 8大部门自动路由
  python3 sync_artifact.py --source /path/to/report.md

  # 手动指定分类
  python3 sync_artifact.py --source /path/to/report.md --category a_series

  # 扫描秘书目录并同步（包含所有部门子目录）
  python3 sync_artifact.py --mailbox ~/.workbuddy/skills/boss-secretary/reports

  # 验证同步状态
  python3 sync_artifact.py --verify ~/.workbuddy/skills/boss-secretary/reports

部门分类 (v5.0):
  a_series     📊 交易部 - A0-A9系列
  oneirology   🌙 做梦部 - 做梦日志与分析
  governance   ⚖️ 治理部 - 宪法、FAQ、工程索引
  audit        🔧 支撑部 - 审计、运营、健康监控
  research     🔬 调研部 - 深度调研、情报分析
  hr           👥 人力资源部 - 绩效、技能、招聘
  knowledge    📚 知识库 - 策略、工具、经验沉淀
  secretary    🏛️ 秘书部 - 临时文件（默认）
'''
    )
    parser.add_argument('--source', '-s', help='源文件路径')
    parser.add_argument('--category', '-c', 
                        choices=VALID_CATEGORIES,
                        help='产物分类（覆盖自动匹配）')
    parser.add_argument('--a-phase', '-a', help='A阶段（A0-A9，仅用于 a_series 分类）')
    parser.add_argument('--mailbox', '-m', help='邮箱目录路径（扫描并同步所有.md文件）')
    parser.add_argument('--hours', type=int, default=0, help='增量模式：只同步最近N小时内的文件（推荐 --hours 4），默认0=全量')
    parser.add_argument('--verify', '-v', help='邮箱目录路径（验证同步状态）')
    parser.add_argument('--quiet', '-q', action='store_true', help='静默模式（减少输出）')
    parser.add_argument('--check-ts', help='验证单个时间戳格式（返回 P0/P1 违规检查）')
    parser.add_argument('--normalize-index', help='规范化 index.json 中的时间戳')
    parser.add_argument('--validate-all', help='批量验证所有产物时间戳（返回违规列表）')
    parser.add_argument('--validate-index', help='验证 index.json 时间戳（返回 P0 违规）')
    
    args = parser.parse_args()
    
    verbose = not args.quiet
    
    # 模式0: 时间戳验证
    if args.check_ts:
        level, normalized, msg = validate_timestamp_strict(args.check_ts)
        print(f"输入: {args.check_ts}")
        print(f"规范: {normalized if normalized else 'N/A'}")
        if level == "OK":
            print(f"结果: ✅ 符合规范")
        elif level == "P2":
            print(f"结果: 🟢 {msg}")
        elif level == "P1":
            print(f"结果: 🟡 {msg}")
        else:
            print(f"结果: 🔴 {msg}")
        return

    # 模式0.5: 批量规范化 index.json
    if args.normalize_index:
        if not os.path.exists(args.normalize_index):
            print(f"❌ 文件不存在: {args.normalize_index}")
            return
        try:
            with open(args.normalize_index, 'r', encoding='utf-8') as f:
                data = json.load(f)
            changed = 0
            for item in data:
                if 'date' in item:
                    is_valid, normalized, _ = validate_timestamp_format(item['date'])
                    if normalized != item['date']:
                        print(f"  {item.get('title', item.get('id'))}: {item['date']} → {normalized}")
                        item['date'] = normalized
                        changed += 1
            if changed > 0:
                with open(args.normalize_index, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"\n✅ 已规范化 {changed} 个时间戳")
            else:
                print("✅ 所有时间戳已符合规范")
        except Exception as e:
            print(f"❌ 处理失败: {e}")
        return

    # 模式0.6: 批量验证所有产物
    if args.validate_all:
        stats = validate_all_artifacts(args.validate_all, verbose=True)
        if stats['P0']:
            print(f"\n🔴 P0 致命违规存在，禁止投递！")
            exit(1)
        return

    # 模式0.7: 验证 index.json
    if args.validate_index:
        stats = validate_index_json(args.validate_index, verbose=True)
        if stats['P0']:
            print(f"\n🔴 P0 致命违规存在，index.json 必须修复！")
            exit(1)
        return
    
    # 模式1: 验证模式
    if args.verify:
        result = verify_mailbox_sync(args.verify, verbose)
        if result['missing_in_frontend']:
            print(f"\n⚠️ 漏同步文件 ({len(result['missing_in_frontend'])}):")
            for f in result['missing_in_frontend'][:10]:
                print(f"   - {f}")
            if len(result['missing_in_frontend']) > 10:
                print(f"   ... 还有 {len(result['missing_in_frontend']) - 10} 个")
        return
    
    # 模式2: 邮箱扫描模式
    if args.mailbox:
        print(f"📂 扫描邮箱目录: {args.mailbox}")
        stats = sync_mailbox(args.mailbox, verbose, hours=args.hours)
        print(f"\n📊 同步统计:")
        print(f"   总文件: {stats['total']}")
        print(f"   成功: {stats['success']} ✅")
        print(f"   失败: {stats['failed']} ❌")
        print(f"   跳过: {stats['skipped']}")
        if stats['categories']:
            print(f"   分类统计:")
            for cat, count in sorted(stats['categories'].items()):
                print(f"     - {cat}: {count}")
        return
    
    # 模式3: 单文件同步模式
    if args.source:
        # 如果是 a_series 分类但未指定 a-phase，尝试自动提取
        a_phase = args.a_phase
        if (args.category == 'a_series' or (not args.category and match_category(os.path.basename(args.source)) == 'a_series')) and not a_phase:
            a_phase = extract_a_phase(args.source)
            if a_phase and verbose:
                print(f"📋 自动识别 A 阶段: {a_phase}")
        
        success = sync_artifact(args.source, args.category, a_phase, verbose)
        
        if success:
            if verbose:
                print(f"\n🎉 同步完成！")
        else:
            if verbose:
                print(f"\n❌ 同步失败！")
            exit(1)
        return
    
    # 无参数模式：显示帮助
    parser.print_help()


if __name__ == '__main__':
    main()
