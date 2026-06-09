#!/usr/bin/env python3
"""
桥接管理API - Bridge Management API
提供桥接层状态、脚本管理等功能
"""

from flask import Blueprint, jsonify, request
import sys
from pathlib import Path
from datetime import datetime
import psutil

bridge_bp = Blueprint('bridge', __name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent


@bridge_bp.route('/status', methods=['GET'])
def get_status():
    """获取桥接层状态"""
    # 获取系统状态
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return jsonify({
        "success": True,
        "status": "running",
        "service": "Dream Universal Gateway Bridge",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_used_mb": memory.used / (1024 * 1024),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free / (1024 * 1024 * 1024)
        },
        "endpoints": {
            "market": "/api/market/*",
            "trade": "/api/trade/*",
            "skill": "/api/skill/*",
            "intent": "/api/intent/*",
            "bridge": "/api/bridge/*"
        }
    })


@bridge_bp.route('/scripts', methods=['GET'])
def list_scripts():
    """列出所有可用的脚本"""
    scripts_dir = PROJECT_ROOT / "scripts"
    
    scripts = []
    if scripts_dir.exists():
        for f in scripts_dir.glob("*.py"):
            if not f.name.startswith("_"):
                scripts.append({
                    "name": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                })
    
    return jsonify({
        "success": True,
        "count": len(scripts),
        "scripts": scripts
    })


@bridge_bp.route('/scripts/<script_name>', methods=['GET'])
def get_script_info(script_name):
    """获取脚本信息"""
    script_path = PROJECT_ROOT / "scripts" / script_name
    
    if not script_path.exists():
        return jsonify({
            "success": False,
            "error": f"Script {script_name} not found"
        }), 404
    
    # 读取脚本头部注释
    description = ""
    with open(script_path, 'r') as f:
        lines = f.readlines()[:50]
        doc_lines = []
        in_doc = False
        for line in lines:
            if '"""' in line or "'''" in line:
                if not in_doc:
                    in_doc = True
                    continue
                else:
                    break
            if in_doc:
                doc_lines.append(line.strip())
        description = "\n".join(doc_lines[:5])
    
    return jsonify({
        "success": True,
        "name": script_name,
        "path": str(script_path),
        "size": script_path.stat().st_size,
        "modified": datetime.fromtimestamp(script_path.stat().st_mtime).isoformat(),
        "description": description or "无描述"
    })


@bridge_bp.route('/skills', methods=['GET'])
def list_bridge_skills():
    """列出桥接层关联的SKILL"""
    skills_dir = PROJECT_ROOT / "skills"
    
    skills = []
    if skills_dir.exists():
        for d in skills_dir.iterdir():
            if d.is_dir():
                skill_md = d / "SKILL.md"
                skills.append({
                    "name": d.name,
                    "has_skill_md": skill_md.exists(),
                    "path": str(d)
                })
    
    return jsonify({
        "success": True,
        "count": len(skills),
        "skills": skills
    })


@bridge_bp.route('/run-script', methods=['POST'])
def run_script():
    """运行指定脚本"""
    data = request.get_json() or {}
    script_name = data.get('script')
    args = data.get('args', [])
    
    if not script_name:
        return jsonify({
            "success": False,
            "error": "script parameter required"
        }), 400
    
    script_path = PROJECT_ROOT / "scripts" / script_name
    if not script_path.exists():
        return jsonify({
            "success": False,
            "error": f"Script {script_name} not found"
        }), 404
    
    import subprocess
    
    try:
        result = subprocess.run(
            ["python3", str(script_path)] + args,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        return jsonify({
            "success": result.returncode == 0,
            "script": script_name,
            "returncode": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:1000]
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "Script execution timeout (>60s)"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })


@bridge_bp.route('/config', methods=['GET'])
def get_config():
    """获取桥接层配置"""
    return jsonify({
        "success": True,
        "config": {
            "host": "127.0.0.1",
            "port": 3847,
            "cors_origins": [
                "http://localhost:3000",
                "http://127.0.0.1:3000"
            ],
            "scripts_dir": str(PROJECT_ROOT / "scripts"),
            "skills_dir": str(PROJECT_ROOT / "skills"),
            "data_dir": str(PROJECT_ROOT / "data"),
            "log_level": "INFO"
        }
    })


@bridge_bp.route('/ping', methods=['GET'])
def ping():
    """心跳检测"""
    return jsonify({
        "success": True,
        "pong": True,
        "timestamp": datetime.now().isoformat()
    })
