/**
 * 告警管理器
 * 周期切换时自动提醒
 */

import { ResearchResult, AlertConfig, Alert, AlertType, AlertChannel } from '../types';
import { HistoryManager } from '../history/history-manager';

export interface AlertHandler {
  send(alert: Alert): Promise<void>;
}

export interface WebhookHandlerConfig {
  url: string;
  method?: 'POST' | 'GET';
  headers?: Record<string, string>;
}

/**
 * 飞书Webhook处理器
 */
export class LarkWebhookHandler implements AlertHandler {
  private webhookUrl: string;

  constructor(webhookUrl: string) {
    this.webhookUrl = webhookUrl;
  }

  async send(alert: Alert): Promise<void> {
    const message = this.formatLarkMessage(alert);

    try {
      const response = await fetch(this.webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(message),
      });

      if (!response.ok) {
        throw new Error(`飞书Webhook发送失败: ${response.status}`);
      }

      console.log('[Alert] 飞书告警发送成功');
    } catch (error) {
      console.error('[Alert] 飞书告警发送失败:', error);
      throw error;
    }
  }

  private formatLarkMessage(alert: Alert): object {
    const colorMap: Record<AlertType, string> = {
      cycle_change: 'red',
      confidence_drop: 'orange',
      allocation_change: 'blue',
      risk_warning: 'red',
      version_fallback: 'yellow',
      daily_report: 'green',
    };

    const iconMap: Record<AlertType, string> = {
      cycle_change: '🔔',
      confidence_drop: '⚠️',
      allocation_change: '📊',
      risk_warning: '🚨',
      version_fallback: '🔄',
      daily_report: '📋',
    };

    return {
      msg_type: 'interactive',
      card: {
        header: {
          title: {
            tag: 'plain_text',
            content: `${iconMap[alert.type]} ${alert.title}`,
          },
          template: colorMap[alert.type] || 'grey',
        },
        elements: [
          {
            tag: 'div',
            text: {
              content: alert.message,
              tag: 'lark_md',
            },
          },
          {
            tag: 'hr',
          },
          {
            tag: 'div',
            fields: [
              {
                is_short: true,
                text: {
                  content: `**类型**\n${alert.type}`,
                  tag: 'lark_md',
                },
              },
              {
                is_short: true,
                text: {
                  content: `**严重程度**\n${alert.severity}`,
                  tag: 'lark_md',
                },
              },
              {
                is_short: true,
                text: {
                  content: `**时间**\n${new Date(alert.timestamp).toLocaleString('zh-CN')}`,
                  tag: 'lark_md',
                },
              },
            ],
          },
          ...(alert.data ? [{
            tag: 'div',
            fields: [{
              is_short: false,
              text: {
                content: `**详情**\n\`\`\`json\n${JSON.stringify(alert.data, null, 2)}\n\`\`\``,
                tag: 'lark_md',
              },
            }],
          }] : []),
        ],
      },
    };
  }
}

/**
 * 邮件处理器
 */
export class EmailHandler implements AlertHandler {
  private smtpConfig: {
    host: string;
    port: number;
    user: string;
    password: string;
    from: string;
    to: string[];
  };

  constructor(smtpConfig: {
    host: string;
    port: number;
    user: string;
    password: string;
    from: string;
    to: string[];
  }) {
    this.smtpConfig = smtpConfig;
  }

  async send(alert: Alert): Promise<void> {
    // 注意：实际使用需要nodemailer库
    console.log('[Alert] 邮件告警（模拟）:', {
      to: this.smtpConfig.to,
      subject: alert.title,
      body: alert.message,
    });

    // 实际实现示例：
    // const nodemailer = require('nodemailer');
    // const transporter = nodemailer.createTransport({
    //   host: this.smtpConfig.host,
    //   port: this.smtpConfig.port,
    //   auth: { user: this.smtpConfig.user, pass: this.smtpConfig.password },
    // });
    // await transporter.sendMail({
    //   from: this.smtpConfig.from,
    //   to: this.smtpConfig.to.join(','),
    //   subject: alert.title,
    //   text: alert.message,
    // });
  }
}

/**
 * Webhook处理器
 */
export class WebhookHandler implements AlertHandler {
  private config: WebhookHandlerConfig;

  constructor(config: WebhookHandlerConfig) {
    this.config = config;
  }

  async send(alert: Alert): Promise<void> {
    try {
      const response = await fetch(this.config.url, {
        method: this.config.method || 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...this.config.headers,
        },
        body: JSON.stringify({
          alert: {
            type: alert.type,
            title: alert.title,
            message: alert.message,
            severity: alert.severity,
            timestamp: alert.timestamp,
            data: alert.data,
          },
        }),
      });

      if (!response.ok) {
        throw new Error(`Webhook发送失败: ${response.status}`);
      }

      console.log('[Alert] Webhook告警发送成功');
    } catch (error) {
      console.error('[Alert] Webhook告警发送失败:', error);
      throw error;
    }
  }
}

/**
 * 告警管理器
 */
export class AlertManager {
  private handlers: Map<AlertChannel, AlertHandler> = new Map();
  private config: AlertConfig;
  private historyManager: HistoryManager | null = null;
  private lastAlertTime: Map<string, number> = new Map();

  constructor(config?: AlertConfig) {
    this.config = {
      enabled: config?.enabled ?? true,
      channels: config?.channels || ['lark'],
      larkWebhookUrl: config?.larkWebhookUrl,
      emailConfig: config?.emailConfig,
      webhookConfigs: config?.webhookConfigs,
      cooldownMinutes: config?.cooldownMinutes || 60,
      severityThresholds: config?.severityThresholds || {
        critical: 0.2,
        high: 0.4,
        medium: 0.6,
        low: 0.8,
      },
    };

    this.initializeHandlers();
  }

  /**
   * 设置历史管理器（用于检测周期变化）
   */
  setHistoryManager(manager: HistoryManager): void {
    this.historyManager = manager;
  }

  /**
   * 初始化处理器
   */
  private initializeHandlers(): void {
    if (this.config.larkWebhookUrl) {
      this.handlers.set('lark', new LarkWebhookHandler(this.config.larkWebhookUrl));
    }

    if (this.config.emailConfig) {
      this.handlers.set('email', new EmailHandler(this.config.emailConfig));
    }

    if (this.config.webhookConfigs) {
      for (const webhookConfig of this.config.webhookConfigs) {
        this.handlers.set('webhook', new WebhookHandler(webhookConfig));
      }
    }
  }

  /**
   * 检查是否应该发送告警（冷却期检查）
   */
  private shouldSend(type: AlertType): boolean {
    const lastTime = this.lastAlertTime.get(type) || 0;
    const cooldownMs = this.config.cooldownMinutes * 60 * 1000;
    return Date.now() - lastTime >= cooldownMs;
  }

  /**
   * 记录告警时间
   */
  private recordAlertTime(type: AlertType): void {
    this.lastAlertTime.set(type, Date.now());
  }

  /**
   * 发送告警
   */
  async send(alert: Alert): Promise<void> {
    if (!this.config.enabled) {
      console.log('[Alert] 告警已禁用');
      return;
    }

    if (!this.shouldSend(alert.type)) {
      console.log(`[Alert] 告警类型 ${alert.type} 处于冷却期，跳过`);
      return;
    }

    console.log(`[Alert] 发送告警: ${alert.title}`);

    const sendPromises: Promise<void>[] = [];

    for (const channel of this.config.channels) {
      const handler = this.handlers.get(channel);
      if (handler) {
        sendPromises.push(handler.send(alert).catch(err => {
          console.error(`[Alert] ${channel} 发送失败:`, err);
        }));
      }
    }

    await Promise.all(sendPromises);
    this.recordAlertTime(alert.type);
  }

  /**
   * 创建周期变化告警
   */
  async checkAndAlertCycleChange(currentResult: ResearchResult): Promise<void> {
    if (!this.historyManager) {
      console.log('[Alert] 未设置历史管理器，跳过周期变化检测');
      return;
    }

    const history = this.historyManager.getHistory({ limit: 2 });
    if (history.length < 2) {
      return;
    }

    const latest = history[0];
    const previous = history[1];

    if (latest.cycle.currentPhase !== previous.cycle.currentPhase) {
      const alert: Alert = {
        id: `cycle_${Date.now()}`,
        type: 'cycle_change',
        title: '经济周期发生变化',
        message: `经济周期从 **${this.translatePhase(previous.cycle.currentPhase)}** 切换到 **${this.translatePhase(latest.cycle.currentPhase)}**`,
        severity: 'high',
        timestamp: new Date().toISOString(),
        data: {
          previousPhase: previous.cycle.currentPhase,
          currentPhase: latest.cycle.currentPhase,
          previousDate: previous.timestamp,
          currentDate: latest.timestamp,
          confidence: latest.cycle.confidence,
        },
      };

      await this.send(alert);
    }
  }

  /**
   * 创建置信度下降告警
   */
  async checkAndAlertConfidenceDrop(currentResult: ResearchResult): Promise<void> {
    if (!this.historyManager) {
      return;
    }

    const history = this.historyManager.getHistory({ limit: 2 });
    if (history.length < 2) {
      return;
    }

    const latest = history[0];
    const drop = latest.confidence - previous.confidence;

    if (drop < -this.config.severityThresholds.critical) {
      const alert: Alert = {
        id: `confidence_${Date.now()}`,
        type: 'confidence_drop',
        title: '模型置信度显著下降',
        message: `置信度从 **${(previous.confidence * 100).toFixed(0)}%** 下降到 **${(latest.confidence * 100).toFixed(0)}%**（下降 ${(Math.abs(drop) * 100).toFixed(0)}%）`,
        severity: Math.abs(drop) < 0.1 ? 'low' : Math.abs(drop) < 0.2 ? 'medium' : 'high',
        timestamp: new Date().toISOString(),
        data: {
          previousConfidence: previous.confidence,
          currentConfidence: latest.confidence,
          drop: Math.abs(drop),
        },
      };

      await this.send(alert);
    }
  }

  /**
   * 创建风险警告
   */
  async sendRiskWarning(
    message: string,
    data?: Record<string, unknown>
  ): Promise<void> {
    const alert: Alert = {
      id: `risk_${Date.now()}`,
      type: 'risk_warning',
      title: '风险警告',
      message,
      severity: 'critical',
      timestamp: new Date().toISOString(),
      data,
    };

    await this.send(alert);
  }

  /**
   * 创建日常报告提醒
   */
  async sendDailyReportNotification(result: ResearchResult): Promise<void> {
    const alert: Alert = {
      id: `daily_${Date.now()}`,
      type: 'daily_report',
      title: '每日资产调研报告',
      message: `当前周期：**${this.translatePhase(result.cycle.currentPhase)}**（置信度 ${(result.cycle.confidence * 100).toFixed(0)}%）\n\nTop 3 推荐标的：\n${result.topSubCategories.slice(0, 3).map((s, i) => `${i + 1}. ${s.subCategory}`).join('\n')}`,
      severity: 'low',
      timestamp: new Date().toISOString(),
      data: {
        cycle: result.cycle.currentPhase,
        confidence: result.cycle.confidence,
        topAssets: result.topSubCategories.slice(0, 5),
      },
    };

    await this.send(alert);
  }

  /**
   * 翻译周期名称
   */
  private translatePhase(phase: string): string {
    const map: Record<string, string> = {
      recovery: '复苏期',
      overheat: '过热期',
      stagflation: '滞胀期',
      recession: '衰退期',
    };
    return map[phase] || phase;
  }
}

// 辅助变量，避免循环引用
const _unused = null;
