# Fox ESS + Amber Electric 电价套利系统

实时读取 Amber 电价，自动通过 Fox ESS API 控制家用逆变器充放电，实现电价套利。

## 系统架构

```
Amber API ──→ 实时电价 + 4h预测
                    │
                    ▼
           ArbitrageStrategy
           (决策引擎，每2分钟)
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
    Force Charge  Self Use  Force Discharge
          │                   │
          └────── Fox ESS API (Scheduler) ──→ 逆变器
                    │
                    ▼
             Telegram 通知
```

## 套利策略

决策按优先级从高到低执行，**每2分钟评估一次**，只在动作发生变化时才向逆变器发送指令。

### 优先级规则

| 优先级 | 触发条件 | 动作 | 典型场景 |
|--------|----------|------|----------|
| 1 | 买入价 ≤ $0.00/kWh | **强制充电** | 电网倒贴钱，尽量多充 |
| 2 | 卖出价 ≥ $1.00/kWh | **强制放电**（忽略所有保护） | 极端 Spike，最高收益 |
| 3 | 卖出价 ≥ $0.50/kWh 或 Spike | **强制放电**（SOC > 15%，利润检查通过） | 常规 Spike 套利 |
| 4 | 卖出价 ≥ $0.20/kWh（适度高价） | **强制放电**（同上） | 高于均价的卖出机会 |
| 5 | 买入价 ≤ $0.12/kWh | **强制充电** | 电价便宜，储能备用 |
| 6 | 在定时充电窗口内 | **强制充电** | 按计划时间充电（可选） |
| 7 | 在定时放电窗口内 | **强制放电** | 按计划时间放电（可选） |
| 默认 | 以上均不满足 | **Self Use** | 太阳能→家用→电池，不干预 |

### 核心保护机制

**利润守卫**：系统跟踪最近 20 次买入价的滚动均值作为电池成本，卖出价必须超出均值 + $0.05 才允许放电，防止亏本套利。

**SOC 边界**：放电不低于 15%，充电不超过 95%。

**Demand Window**：可配置高峰时段（夏/冬），在此窗口内价格不够极端时不放电，避免触发需量电费。

### 决策示例（当前实测）

```
凌晨 3:00  买 $0.062  卖 -$0.024  →  Force Charge（买入价低于 $0.12）
下午 5:30  买 $0.31   卖 $0.58    →  Force Discharge（Spike 套利）
其他时段                           →  Self Use
```

## 项目结构

```
├── main.py          # 主循环：轮询价格 + 驱动套利 + Telegram 通知
├── strategy.py      # 套利决策引擎
├── fox_client.py    # Fox ESS Open API 封装（认证、读取、控制）
├── amber_client.py  # Amber Electric API 封装（实时价格、预测）
├── notifier.py      # Telegram 通知 + 图表生成
├── config.yaml      # 所有阈值和配置
└── .env             # API 密钥（不提交）
```

## Fox ESS API 说明

认证使用 HMAC-MD5 签名，签名字符串格式（两处易错）：

```
/op/v0{path}\r\n{api_key}\r\n{timestamp_ms}
```

- 路径必须包含完整前缀 `/op/v0`
- `\r\n` 是字面量 4 个字符，**不是** CRLF 换行

模式控制全部通过 `POST /op/v0/device/scheduler/enable` 实现：

```python
# ForceDischarge 示例
{
  "deviceSN": "...",
  "groups": [{
    "enable": 1, "startHour": 0, "startMinute": 0,
    "endHour": 23, "endMinute": 59,
    "workMode": "ForceDischarge",
    "fdPwr": 5000,   # 放电功率（瓦）
    "fdSoc": 15,     # 停止放电 SOC%
    "minSocOnGrid": 15
  }]
}
```

> `forceDischargeTime/set` 端点不存在，务必使用 scheduler。

## 环境配置

### `.env`

```env
AMBER_API_KEY=...
FOX_API_KEY=...
FOX_DEVICE_SN=          # 留空则自动发现
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### `config.yaml` 关键参数

```yaml
arbitrage:
  enabled: true           # false = 只监控，不控制逆变器

thresholds:
  sell_high: 0.50         # Spike 放电触发价（$/kWh）
  sell_extreme: 1.00      # 极端 Spike，忽略所有保护
  buy_max: 0.12           # 便宜充电触发价
  negative_price: 0.0     # 负电价触发强制充电
  min_profit_margin: 0.05 # 卖出价需超过充电均价 + 此值

battery:
  min_soc: 15
  max_soc: 95
  max_discharge_kw: 5.0   # QLD 出口限制 5kW
```

## 安装与运行

```bash
pip install -r requirements.txt
cp .env.example .env      # 填入 API 密钥

# 测试（不控制逆变器）
python3 main.py --dry-run

# 查看当前状态
python3 main.py --status

# 正式运行
python3 main.py
```

## Telegram 指令

在 Telegram 向 Bot 发送任意消息 → 回复当前电价  
发送 `/chart` 或 `/图表` → 发送 7 天价格走势图

---

## 改进路线图

详见下方 [算法改进](#算法改进) 部分。

---

## 算法改进

### 当前局限性

现有策略是**纯反应式**的：只看当前价格，每 2 分钟独立决策，不感知全天价格形态，不考虑明天的太阳能产量。

### 改进一：太阳能产量预测（最高价值）

**问题**：晴天时太阳能会在上午把电池充满，所以前一天晚上完全不需要从电网充电。阴天则相反，必须提前充。当前策略无法区分这两种情况。

**方案**：接入 [Open-Meteo](https://open-meteo.com)（免费，无需 API key）获取次日太阳辐射预测。

```python
# 示例：Brisbane 明日太阳辐射预测
GET https://api.open-meteo.com/v1/forecast
  ?latitude=-27.4698&longitude=153.0251
  &hourly=shortwave_radiation,cloud_cover
  &forecast_days=2&timezone=Australia/Brisbane
```

**决策逻辑**：

```
明日预测太阳能产量
  ≥ 电池容量 × 0.8  →  夜间不从电网充电（太阳能够用）
  < 电池容量 × 0.4  →  夜间主动充电到 80%（阴天备用）
  中间              →  仅在价格极便宜时充
```

**预期收益**：减少不必要的电网充电，降低充电成本约 30-40%。

---

### 改进二：全天价格规划（Day-Ahead Scheduler）

**问题**：Amber 提供全天预测价格，但当前策略只看当前 1 个时段，不做全局最优规划。

**方案**：每天早上 6:00 用当天的预测价格计算最优充放电计划：

```
1. 获取 Amber 全天预测（每 30 分钟一个价格点）
2. 找到最低 N 个价格时段 → 安排充电
3. 找到最高 M 个价格时段 → 安排放电
4. 约束：放电总量 ≤ 可用电量，充电总量 ≤ 电池剩余容量
5. 生成当天的充放电时刻表，写入 Fox scheduler
```

**预期收益**：避免在 $0.12 充电但 1 小时后有 $0.08 更便宜价格的情况；提前为已知 Spike 保留 SOC。

---

### 改进三：动态目标 SOC

**问题**：当前硬编码 `max_soc=95%`，不管明天能不能靠太阳能补回来。

**方案**：根据明日天气和下一个预测 Spike 时间动态调整目标 SOC：

| 情况 | 目标 SOC |
|------|----------|
| 明日晴天 + 无夜间 Spike 预测 | 50%（省电池寿命） |
| 明日多云 + 下午有 Spike | 80%（确保有货放） |
| 明日阴天 + 有 Spike | 95%（最大化套利） |
| 极端负电价（< -$0.05） | 95%（白给的电） |

---

### 改进四：电池寿命成本

**问题**：当前利润计算没有计入每次充放电对电池的损耗。

**方案**：在 `_is_profitable()` 中加入循环成本：

```python
BATTERY_COST_PER_KWH = 0.04  # 约 $0.04/kWh（10年/10000次寿命估算）

def _is_profitable(self, sell_price):
    true_cost = self._avg_charge_cost + BATTERY_COST_PER_KWH
    return sell_price >= true_cost + self.cfg["thresholds"]["min_profit_margin"]
```

**意义**：避免为了 $0.01 利润白白磨损电池。

---

### 改进优先级建议

| 优先级 | 改进项 | 难度 | 预期年收益提升 |
|--------|--------|------|----------------|
| ⭐⭐⭐ | 太阳能预测（改进一） | 低（Open-Meteo 免费） | ~$200-400 |
| ⭐⭐ | 全天价格规划（改进二） | 中 | ~$100-200 |
| ⭐⭐ | 动态目标 SOC（改进三） | 低 | ~$50-100（电池寿命） |
| ⭐ | 电池寿命成本（改进四） | 低 | 间接（延长电池寿命） |
