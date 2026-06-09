#!/usr/bin/env python3
"""
交易执行API - Trade Execution API
封装交易执行逻辑，支持模拟盘和实盘
"""

from flask import Blueprint, jsonify, request
import sys
from pathlib import Path
from datetime import datetime
import uuid

# 添加scripts路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

try:
    from okx_cli import OKXCLI
    OKX_AVAILABLE = True
except ImportError:
    OKX_AVAILABLE = False

trade_bp = Blueprint('trade', __name__)

# 模拟订单存储
MOCK_ORDERS = {}


@trade_bp.route('/order', methods=['POST'])
def place_order():
    """下单接口
    
    Request Body:
        inst_id: 交易对
        side: buy/sell
        pos_side: long/short/net
        sz: 数量
        ord_type: market/limit (optional, default: market)
        px: 价格 (optional, 市价单不需要)
    """
    # 验证 Content-Type
    if not request.is_json:
        return jsonify({
            "success": False,
            "error": "Content-Type must be application/json"
        }), 400
    
    data = request.get_json() or {}
    
    # 验证必填参数
    required = ['inst_id', 'side', 'pos_side', 'sz']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({
            "success": False,
            "error": f"Missing required fields: {missing}",
            "code": "MISSING_REQUIRED_FIELDS"
        }), 400
    
    # 验证参数格式
    valid_sides = ['buy', 'sell']
    if data['side'] not in valid_sides:
        return jsonify({
            "success": False,
            "error": f"Invalid side. Must be one of: {valid_sides}",
            "code": "INVALID_SIDE"
        }), 400
    
    valid_pos_sides = ['long', 'short', 'net']
    if data['pos_side'] not in valid_pos_sides:
        return jsonify({
            "success": False,
            "error": f"Invalid pos_side. Must be one of: {valid_pos_sides}",
            "code": "INVALID_POS_SIDE"
        }), 400
    
    # 验证数量
    try:
        sz = float(data['sz'])
        if sz <= 0:
            return jsonify({
                "success": False,
                "error": "sz must be positive",
                "code": "INVALID_SIZE"
            }), 400
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "error": "sz must be a valid number",
            "code": "INVALID_SIZE"
        }), 400
    
    # 验证订单类型
    ord_type = data.get('ord_type', 'market')
    valid_ord_types = ['market', 'limit']
    if ord_type not in valid_ord_types:
        return jsonify({
            "success": False,
            "error": f"Invalid ord_type. Must be one of: {valid_ord_types}",
            "code": "INVALID_ORD_TYPE"
        }), 400
    
    # 如果是限价单，验证价格
    if ord_type == 'limit':
        if 'px' not in data:
            return jsonify({
                "success": False,
                "error": "px required for limit orders",
                "code": "MISSING_PRICE"
            }), 400
        try:
            px = float(data['px'])
            if px <= 0:
                return jsonify({
                    "success": False,
                    "error": "px must be positive",
                    "code": "INVALID_PRICE"
                }), 400
        except (ValueError, TypeError):
            return jsonify({
                "success": False,
                "error": "px must be a valid number",
                "code": "INVALID_PRICE"
            }), 400
    
    # 如果有 OKX CLI，执行真实下单
    if OKX_AVAILABLE:
        try:
            okx = OKXCLI(profile='paper')
            result = okx.place_order(
                inst_id=data['inst_id'],
                side=data['side'],
                pos_side=data['pos_side'],
                sz=int(data['sz']),
                ord_type=data.get('ord_type', 'market'),
                price=float(data['px']) if 'px' in data else None
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    # 模拟订单（OKX CLI 不可用时）
    order_id = f"demo_{uuid.uuid4().hex[:12]}"
    order = {
        "ord_id": order_id,
        "inst_id": data['inst_id'],
        "side": data['side'],
        "pos_side": data['pos_side'],
        "sz": data['sz'],
        "px": data.get('px', 'market'),
        "ord_type": data.get('ord_type', 'limit'),
        "state": "live",
        "timestamp": datetime.now().isoformat()
    }
    
    MOCK_ORDERS[order_id] = order
    
    return jsonify({
        "success": True,
        "order": order,
        "mode": "simulation"
    })


@trade_bp.route('/order/<order_id>', methods=['GET'])
def get_order(order_id):
    """查询订单"""
    order = MOCK_ORDERS.get(order_id)
    if order:
        return jsonify({
            "success": True,
            "order": order
        })
    
    return jsonify({
        "success": False,
        "error": "Order not found"
    }), 404


@trade_bp.route('/orders', methods=['GET'])
def get_orders():
    """查询所有订单"""
    status = request.args.get('state', 'all')
    
    if status == 'all':
        orders = list(MOCK_ORDERS.values())
    else:
        orders = [o for o in MOCK_ORDERS.values() if o['state'] == status]
    
    return jsonify({
        "success": True,
        "count": len(orders),
        "orders": orders
    })


@trade_bp.route('/order/<order_id>', methods=['DELETE'])
def cancel_order(order_id):
    """取消订单"""
    if order_id in MOCK_ORDERS:
        MOCK_ORDERS[order_id]['state'] = 'cancelled'
        return jsonify({
            "success": True,
            "message": "Order cancelled",
            "order_id": order_id
        })
    
    return jsonify({
        "success": False,
        "error": "Order not found"
    }), 404


@trade_bp.route('/positions', methods=['GET'])
def get_positions():
    """获取持仓"""
    # 模拟持仓数据
    return jsonify({
        "success": True,
        "positions": [
            {
                "inst_id": "BTC-USDT-SWAP",
                "pos_side": "long",
                "sz": "0.1",
                "avg_px": "95000.00",
                "pnl": "100.00",
                "upl": "50.00",
                "leverage": "5"
            }
        ]
    })


@trade_bp.route('/balance', methods=['GET'])
def get_balance():
    """获取账户余额
    
    Query Parameters:
        exchange: 交易所类型 (okx, binance, etc.) - 默认为 okx
        accountLabel: 账户名/标签 - 默认为 空
        environment: 账户类型 (live, demo) - 默认为 demo
        symbol: 币种 (USDT, BTC, etc.) - 默认为 USDT
    """
    exchange = request.args.get('exchange', 'okx').lower()
    account_label = request.args.get('accountLabel', '')
    environment = request.args.get('environment', 'demo')
    symbol = request.args.get('symbol', 'USDT')
    
    # 根据账户名生成不同的模拟数据（便于测试区分）
    def gen_mock_balance(label: str, is_live: bool) -> dict:
        # 不同账户名映射到不同余额
        label_seed = sum(ord(c) for c in label) if label else 0
        base = 5000 + label_seed * 100  # 不同账户基础余额不同
        total = base + (200 if is_live else 0)  # 实盘多加200
        available = total * 0.8
        margin = total * 0.2
        return {
            "success": True,
            "data": {
                "exchange": exchange,
                "environment": environment,
                "currency": symbol,
                "accountLabel": label,
                "totalEquity": total,
                "available": available,
                "marginUsed": margin,
                "unrealizedPnl": -50.0 if is_live else 50.0,  # 实盘模拟亏损，模拟盘盈利
                "positions": []
            }
        }
    
    # 检查OKX API凭证是否配置
    def check_okx_credentials() -> bool:
        import os
        return bool(os.environ.get('OKX_API_KEY') and os.environ.get('OKX_SECRET_KEY') and os.environ.get('OKX_PASSPHRASE'))
    
    # 检查是否配置了实盘API
    if environment == 'live':
        # 先检查凭证是否配置
        if not check_okx_credentials():
            return jsonify({
                "success": False,
                "error": "实盘账户未配置API凭证。请在系统环境变量中设置 OKX_API_KEY、OKX_SECRET_KEY、OKX_PASSPHRASE",
                "mode": "live",
                "data": {
                    "exchange": exchange,
                    "environment": environment,
                    "currency": symbol,
                    "accountLabel": account_label,
                    "totalEquity": 0,
                    "available": 0,
                    "marginUsed": 0,
                    "unrealizedPnl": 0,
                    "positions": []
                }
            })
        
        # 实盘模式 - 需要真实的OKX API调用
        if OKX_AVAILABLE:
            try:
                okx = OKXCLI(profile='live')
                # 获取账户余额 (使用okx CLI的get_balance方法)
                result = okx.get_balance()
                
                if result.get('success'):
                    balance_data = result.get('data', {})
                    # 解析USDT余额
                    usdt_data = balance_data.get('USDT', {})
                    total_equity = float(usdt_data.get('equity', '0'))
                    available = float(usdt_data.get('available', '0'))
                    return jsonify({
                        "success": True,
                        "data": {
                            "exchange": exchange,
                            "environment": environment,
                            "currency": symbol,
                            "accountLabel": account_label,
                            "totalEquity": total_equity,
                            "available": available,
                            "marginUsed": total_equity - available,
                            "unrealizedPnl": 0,
                            "positions": []
                        }
                    })
                else:
                    return jsonify({
                        "success": False,
                        "error": f"获取实盘余额失败: {result.get('error', '未知错误')}",
                        "mode": "live",
                        "data": {
                            "exchange": exchange,
                            "environment": environment,
                            "currency": symbol,
                            "accountLabel": account_label,
                            "totalEquity": 0,
                            "available": 0,
                            "marginUsed": 0,
                            "unrealizedPnl": 0,
                            "positions": []
                        }
                    }), 500
            except Exception as e:
                return jsonify({
                    "success": False,
                    "error": f"获取实盘余额失败: {str(e)}",
                    "mode": "live"
                }), 500
        
        # 实盘API不可用但请求实盘模式，返回错误提示
        return jsonify({
            "success": False,
            "error": f"实盘账户 [{account_label}] 未配置或API不可用",
            "mode": "live",
            "data": None
        }), 404
    
    # 模拟盘模式 - 根据账户名返回不同模拟数据
    return jsonify({
        "success": True,
        "data": {
            "exchange": exchange,
            "environment": environment,
            "currency": symbol,
            "accountLabel": account_label,
            "totalEquity": 5000 if not account_label else 5000 + sum(ord(c) for c in account_label) * 50,
            "available": 4000 if not account_label else (5000 + sum(ord(c) for c in account_label) * 50) * 0.8,
            "marginUsed": 1000 if not account_label else (5000 + sum(ord(c) for c in account_label) * 50) * 0.2,
            "unrealizedPnl": 50.0,
            "positions": []
        }
    })


@trade_bp.route('/set-leverage', methods=['POST'])
def set_leverage():
    """设置杠杆倍数"""
    data = request.get_json() or {}
    
    required = ['inst_id', 'leverage', 'mgn_mode']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({
            "success": False,
            "error": f"Missing required fields: {missing}"
        }), 400
    
    return jsonify({
        "success": True,
        "message": "Leverage set",
        "inst_id": data['inst_id'],
        "leverage": data['leverage'],
        "mgn_mode": data['mgn_mode']
    })


@trade_bp.route('/close-position', methods=['POST'])
def close_position():
    """平仓"""
    data = request.get_json() or {}
    inst_id = data.get('inst_id')
    pos_side = data.get('pos_side')
    
    if not inst_id:
        return jsonify({
            "success": False,
            "error": "inst_id required"
        }), 400
    
    return jsonify({
        "success": True,
        "message": "Position closed",
        "inst_id": inst_id,
        "pos_side": pos_side or "all"
    })


@trade_bp.route('/history', methods=['GET'])
def get_trade_history():
    """获取交易历史"""
    inst_id = request.args.get('inst_id')
    
    return jsonify({
        "success": True,
        "history": [],
        "note": "Trade history will be synced from OKX"
    })
