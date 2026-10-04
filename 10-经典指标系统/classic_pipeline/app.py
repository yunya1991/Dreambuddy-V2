"""经典指标系统 C0-C8 模块化 API 服务（Flask app factory）。

当前为骨架阶段：
- core hooks（CORS/guards）已注册
- 各阶段 Blueprint 已注册（暂为空，路由随迁移逐步填充）
- 单体 ml_trade_service.py 仍承载全部 431 路由，Blueprint 路由将逐步迁入

最终态：ml_trade_service.py 缩减为 `from classic_pipeline.app import app`。
"""
from __future__ import annotations

from flask import Flask

from classic_pipeline.core.http import register_hooks


def create_app() -> Flask:
    """创建并配置 Flask 应用实例。"""
    app = Flask(__name__)

    # 注册横切 HTTP hooks（CORS / characterization 守卫 / 退役路由守卫）
    register_hooks(app)

    # 注册各阶段 Blueprint（骨架阶段：Blueprint 已创建，路由随迁移逐步填充）
    from classic_pipeline.c1_universe.blueprint import bp as c1_universe_bp
    from classic_pipeline.signals.blueprint import bp as c2_signals_bp
    from classic_pipeline.backtest.blueprint import bp as c3_backtest_bp
    from classic_pipeline.risk.blueprint import bp as c4_risk_bp
    from classic_pipeline.plan.blueprint import bp as c6_plan_bp

    app.register_blueprint(c1_universe_bp)
    app.register_blueprint(c2_signals_bp)
    app.register_blueprint(c3_backtest_bp)
    app.register_blueprint(c4_risk_bp)
    app.register_blueprint(c6_plan_bp)

    # TODO: 待迁移阶段的 Blueprint
    # from classic_pipeline.c0_env_scan.blueprint import bp as c0_bp
    # from classic_pipeline.c5_optimize.blueprint import bp as c5_bp
    # from classic_pipeline.c7_monitor.blueprint import bp as c7_bp
    # from classic_pipeline.c8_attribution.blueprint import bp as c8_bp
    # from classic_pipeline.agents.blueprint import bp as agents_bp

    return app


app = create_app()
