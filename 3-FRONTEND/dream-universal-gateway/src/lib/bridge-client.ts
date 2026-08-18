// Bridge API Client Module
// Frontend unified interface for calling bridge layer

const BRIDGE_BASE_URL = process.env.NEXT_PUBLIC_BRIDGE_URL || 'http://127.0.0.1:3847';

interface BridgeResponse<T = any> {
  success: boolean;
  error?: string;
  data?: T;
  [key: string]: any;
}

// 通用请求函数
async function bridgeRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<BridgeResponse<T>> {
  try {
    const response = await fetch(`${BRIDGE_BASE_URL}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    return await response.json();
  } catch (error) {
    console.error(`Bridge API Error [${endpoint}]:`, error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Network error',
    };
  }
}

// ========== 市场数据 API ==========

export const MarketAPI = {
  // 获取行情
  async getTicker(instId: string = 'BTC-USDT-SWAP') {
    return bridgeRequest(`/api/market/ticker/${instId}`);
  },

  // 获取K线
  async getCandles(instId: string, bar: string = '1H', limit: number = 100) {
    return bridgeRequest(`/api/market/candles/${instId}?bar=${bar}&limit=${limit}`);
  },

  // 批量获取行情
  async getMultiTicker(instIds: string[]) {
    return bridgeRequest('/api/market/multi-ticker', {
      method: 'POST',
      body: JSON.stringify({ inst_ids: instIds }),
    });
  },

  // 获取交易对列表
  async getTradePairs() {
    return bridgeRequest('/api/market/pairs');
  },

  // 获取资金费率
  async getFundingRate(instId: string) {
    return bridgeRequest(`/api/market/funding-rate/${instId}`);
  },
};

// ========== 交易执行 API ==========

export const TradeAPI = {
  // 下单
  async placeOrder(params: {
    inst_id: string;
    side: 'buy' | 'sell';
    pos_side: 'long' | 'short' | 'net';
    sz: string;
    px: string;
    ord_type?: 'limit' | 'market';
  }) {
    return bridgeRequest('/api/trade/order', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  // 查询订单
  async getOrder(orderId: string) {
    return bridgeRequest(`/api/trade/order/${orderId}`);
  },

  // 查询所有订单
  async getOrders(state?: string) {
    const query = state ? `?state=${state}` : '';
    return bridgeRequest(`/api/trade/orders${query}`);
  },

  // 取消订单
  async cancelOrder(orderId: string) {
    return bridgeRequest(`/api/trade/order/${orderId}`, {
      method: 'DELETE',
    });
  },

  // 获取持仓
  async getPositions() {
    return bridgeRequest('/api/trade/positions');
  },

  // 获取余额
  async getBalance() {
    return bridgeRequest('/api/trade/balance');
  },

  // 设置杠杆
  async setLeverage(instId: string, leverage: string, mgnMode: string = 'isolated') {
    return bridgeRequest('/api/trade/set-leverage', {
      method: 'POST',
      body: JSON.stringify({
        inst_id: instId,
        leverage,
        mgn_mode: mgnMode,
      }),
    });
  },

  // 平仓
  async closePosition(instId: string, posSide?: string) {
    return bridgeRequest('/api/trade/close-position', {
      method: 'POST',
      body: JSON.stringify({ inst_id: instId, pos_side: posSide }),
    });
  },
};

// ========== SKILL 路由 API ==========

export const SkillAPI = {
  // 列出所有SKILL
  async listSkills() {
    return bridgeRequest('/api/skill/list');
  },

  // 执行SKILL
  async executeSkill(skillKey: string, params?: any, context?: any) {
    return bridgeRequest('/api/skill/execute', {
      method: 'POST',
      body: JSON.stringify({
        skill: skillKey,
        params: params || {},
        context: context || {},
      }),
    });
  },

  // 执行流水线
  async executePipeline(params: {
    symbol: string;
    direction: 'long' | 'short';
    phases?: string[];
  }) {
    return bridgeRequest('/api/skill/pipeline', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  // 查询任务状态
  async getTaskStatus(taskId: string) {
    return bridgeRequest(`/api/skill/status/${taskId}`);
  },

  // 获取阶段信息
  async getPhaseInfo(phase: string) {
    return bridgeRequest(`/api/skill/phase-info/${phase}`);
  },
};

// ========== 意图路由 API ==========

export const IntentAPI = {
  // 路由用户输入
  async route(text: string) {
    return bridgeRequest('/api/intent/route', {
      method: 'POST',
      body: JSON.stringify({ text }),
    });
  },

  // 批量路由
  async batchRoute(inputs: string[]) {
    return bridgeRequest('/api/intent/batch', {
      method: 'POST',
      body: JSON.stringify({ inputs }),
    });
  },

  // 获取示例
  async getExamples() {
    return bridgeRequest('/api/intent/examples');
  },
};

// ========== 桥接管理 API ==========

export const BridgeAPI = {
  // 健康检查
  async health() {
    return bridgeRequest('/api/health');
  },

  // 获取状态
  async getStatus() {
    return bridgeRequest('/api/bridge/status');
  },

  // 列出脚本
  async listScripts() {
    return bridgeRequest('/api/bridge/scripts');
  },

  // 获取脚本信息
  async getScriptInfo(scriptName: string) {
    return bridgeRequest(`/api/bridge/scripts/${scriptName}`);
  },

  // 列出SKILL
  async listSkills() {
    return bridgeRequest('/api/bridge/skills');
  },

  // 心跳
  async ping() {
    return bridgeRequest('/api/bridge/ping');
  },
};

export default {
  Market: MarketAPI,
  Trade: TradeAPI,
  Skill: SkillAPI,
  Intent: IntentAPI,
  Bridge: BridgeAPI,
};
