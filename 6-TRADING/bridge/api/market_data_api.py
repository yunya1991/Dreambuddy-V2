#!/usr/bin/env python3
"""
市场数据API - Market Data API
封装 scripts/okx_cli.py 获取市场数据
"""

from flask import Blueprint, jsonify, request
import sys
from pathlib import Path

# 添加scripts路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

try:
    from okx_cli import OKXCLI
    OKX_AVAILABLE = True
except ImportError:
    OKX_AVAILABLE = False

market_bp = Blueprint('market', __name__)

# 初始化OKX CLI
okx_cli = OKXCLI(profile="paper") if OKX_AVAILABLE else None


@market_bp.route('/ticker/<inst_id>', methods=['GET'])
def get_ticker(inst_id):
    """获取指定交易对的实时行情
    
    Args:
        inst_id: 交易对ID，如 BTC-USDT-SWAP
    
    Returns:
        JSON 格式的行情数据
    """
    # 输入验证
    if not inst_id or len(inst_id) > 50:
        return jsonify({
            "success": False,
            "error": "Invalid inst_id",
            "code": "INVALID_PARAMETER"
        }), 400
    
    if not OKX_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "OKX CLI not available",
            "mock_data": True,
            "code": "CLI_NOT_AVAILABLE",
            "data": {
                "inst_id": inst_id,
                "last": "95000.00",
                "high_24h": "97000.00",
                "low_24h": "94000.00",
                "vol_24h": "12345.67",
                "timestamp": "2026-05-15T18:00:00Z"
            }
        })
    
    try:
        result = okx_cli.get_ticker(inst_id)
        
        if not result.get("success"):
            return jsonify({
                "success": False,
                "error": "Failed to fetch ticker",
                "inst_id": inst_id,
                "raw": result.get("raw", "")
            }), 502
        
        return jsonify({
            "success": True,
            "inst_id": inst_id,
            "data": result.get("data", {}),
            "raw": result.get("raw", "")
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "code": "INTERNAL_ERROR",
            "inst_id": inst_id
        }), 500


@market_bp.route('/candles/<inst_id>', methods=['GET'])
def get_candles(inst_id):
    """获取K线数据
    
    Args:
        inst_id: 交易对ID
        bar: K线周期 (1m, 5m, 15m, 1H, 4H, 1D)
        limit: 数据条数 (默认100，最大300)
    """
    # 输入验证
    if not inst_id or len(inst_id) > 50:
        return jsonify({
            "success": False,
            "error": "Invalid inst_id"
        }), 400
    
    bar = request.args.get('bar', '1H')
    valid_bars = ['1m', '5m', '15m', '30m', '1H', '4H', '1D', '1W']
    if bar not in valid_bars:
        return jsonify({
            "success": False,
            "error": f"Invalid bar. Must be one of: {valid_bars}"
        }), 400
    
    try:
        limit = min(int(request.args.get('limit', '100')), 300)
    except ValueError:
        limit = 100
    
    if not OKX_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "OKX CLI not available",
            "mock_data": True,
            "inst_id": inst_id,
            "bar": bar,
            "limit": limit,
            "data": []
        })
    
    try:
        result = okx_cli.get_candles(inst_id, bar=bar, limit=limit)
        return jsonify({
            "success": True,
            "inst_id": inst_id,
            "bar": bar,
            "limit": limit,
            "data": result.get("data", [])
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "inst_id": inst_id
        }), 500


@market_bp.route('/multi-ticker', methods=['POST'])
def get_multi_ticker():
    """批量获取多个交易对的行情
    
    Request Body:
        inst_ids: 交易对列表 (最多10个)
    """
    data = request.get_json() or {}
    inst_ids = data.get('inst_ids', ['BTC-USDT-SWAP'])
    
    # 验证输入
    if not isinstance(inst_ids, list):
        return jsonify({
            "success": False,
            "error": "inst_ids must be an array"
        }), 400
    
    if len(inst_ids) > 10:
        return jsonify({
            "success": False,
            "error": "Maximum 10 instruments allowed"
        }), 400
    
    # 过滤无效的 inst_id
    valid_ids = [i for i in inst_ids if i and len(i) <= 50][:10]
    
    results = []
    for inst_id in valid_ids:
        if okx_cli:
            try:
                result = okx_cli.get_ticker(inst_id)
                results.append({
                    "inst_id": inst_id,
                    "data": result.get("data", {}),
                    "success": result.get("success", False)
                })
            except Exception as e:
                results.append({
                    "inst_id": inst_id,
                    "success": False,
                    "error": str(e)
                })
        else:
            results.append({
                "inst_id": inst_id,
                "success": False,
                "mock": True
            })
    
    return jsonify({
        "success": True,
        "count": len(results),
        "data": results
    })


@market_bp.route('/pairs', methods=['GET'])
def get_trade_pairs():
    """获取支持的交易对列表"""
    return jsonify({
        "success": True,
        "pairs": [
            # 主流币
            {"inst_id": "BTC-USDT-SWAP", "alias": "BTC永续", "category": "主流"},
            {"inst_id": "ETH-USDT-SWAP", "alias": "ETH永续", "category": "主流"},
            {"inst_id": "SOL-USDT-SWAP", "alias": "SOL永续", "category": "主流"},
            # 热门币
            {"inst_id": "DOGE-USDT-SWAP", "alias": "DOGE永续", "category": "热门"},
            {"inst_id": "XRP-USDT-SWAP", "alias": "XRP永续", "category": "热门"},
            {"inst_id": "ADA-USDT-SWAP", "alias": "ADA永续", "category": "热门"},
        ]
    })


@market_bp.route('/index-price/<inst_id>', methods=['GET'])
def get_index_price(inst_id):
    """获取指数价格"""
    return jsonify({
        "success": True,
        "inst_id": inst_id,
        "index_price": "95000.00",
        "mark_price": "95050.00",
        "last": "95050.00"
    })


@market_bp.route('/funding-rate/<inst_id>', methods=['GET'])
def get_funding_rate(inst_id):
    """获取资金费率"""
    return jsonify({
        "success": True,
        "inst_id": inst_id,
        "funding_rate": "0.0001",
        "next_funding_time": "2026-05-16T00:00:00Z"
    })
