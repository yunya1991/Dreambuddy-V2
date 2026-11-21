# 手机端适配器参考 — mobile-reservation-assist

本组件把"预约作业"翻译为"手机动作序列"，平台差异只允许出现在 `phone_adapters/<平台>.py`。

## 通用流程（BasePhoneAdapter）

```
open_app(app) → goto(route) → search(field,value) → select_session → select_tier
→ fill_identity(field)? → goto_order_page → stop(before_payment)
```

## 动作原语

| action | 含义 | 关键字段 |
|---|---|---|
| open_app | 打开官方 App | app（包名） |
| goto | 进入目标路径 | route |
| search | 检索目标 | field / value |
| select_session | 选场次 | value |
| select_tier | 选票档/号源 | value |
| fill_identity | 预填实名 | field |
| goto_order_page | 进入官方下单页并预填 | — |
| stop | 停在支付前（人工确认） | reason=before_payment |

## 平台占位

| NAME | 官方 App 包名 | 备注 |
|---|---|---|
| railway | com.MobileTicket | 车票/余票 |
| damai | cn.damai | 演出 |
| bilibili | tv.danmaku.bili | 会员购 |
| maoyan | com.sankuai.movie | 电影/演出 |
| medical | （按医院实例配置） | 挂号/疫苗 |
| gov | （按政务实例配置） | 签证/场馆 |

> P1 才细化真实选择器（resource-id / text / 坐标）与异常分支（验证码、登录失效）。

## 硬约束

- 任何动作序列都不得出现支付/锁座/占座步骤（`assert_no_payment` 构建即校验）。
- 终态停在官方下单页并预填，最终确认与支付由人工完成。
