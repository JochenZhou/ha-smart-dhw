# 智能热水 Smart DHW

[![一键添加到 HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JochenZhou&repository=ha-smart-dhw&category=integration)
[![打开 Home Assistant 添加集成](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=smart_dhw)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

按**室外温度分档**自动设定燃气热水器的洗澡水温 / 日常水温，并可选同步下发到热水器实体。
分档表出厂内置，家里的实际管损由你**按档校准**，不会被一次校准压成一条直线。

- 测试环境：Home Assistant 2026.9（`hacs.json` 声明最低 2024.6）
- 纯本地逻辑（`iot_class: local_polling`），无网络请求、无外部依赖、无账号

## 安装

**HACS（推荐）**

1. 点上面的「一键添加到 HACS」徽章；若未生效，手动在 HACS → 右上角三点 → 自定义存储库，
   添加 `https://github.com/JochenZhou/ha-smart-dhw`，类别选「集成 / Integration」。
2. 在 HACS 里安装「智能热水」，**重启 Home Assistant**。
3. 设置 → 设备与服务 → 添加集成 → 搜「智能热水」，填入传感器。

**手动**

把 `custom_components/smart_dhw` 整个目录复制到 HA 的 `/config/custom_components/` 下，重启 HA。

## 配置

| 字段 | 说明 |
|------|------|
| 名称 | 设备名，用于生成实体 ID |
| 室外温度传感器 | **必须是摄氏温度实体**（湿度、华氏实体会被拒绝） |
| 备用室外温度 | 可选；主传感器不可用时接管 |
| 室内温度 / 备用 | 可选；同样必须是温度实体 |
| 热水器设备目标温度 | 可选；填热水器的 `number.*` 目标温度实体，用于自动下发 |
| 启用室内温度微调 | ±1 °C，冷天室内偏冷时略微上调 |
| 自动同步设备目标 | 是否把结果写回热水器 |
| 分档迟滞 / 换档需持续 | 防抖：温度需越过阈值 1 °C 且持续 N 分钟才换档 |

> 上下限（洗澡下限/上限、日常下限/上限）是**实体**，在设备页面调，不在配置流里。

## 实体

| 实体 | 作用 |
|------|------|
| `number.*_洗澡水温` | 当前档洗澡水温 — **写它 = 校准当前档**（属性含 requested / applied / 是否被限制） |
| `number.*_日常水温` | 当前档日常水温 — 同上（独立表） |
| `number.*_洗澡下限 / 洗澡上限 / 日常下限 / 日常上限` | 上下限（配置类，绝对范围 30–50 °C，>45 会提示烫伤风险） |
| `sensor.*_洗澡校准偏移` | 当前档偏移（°C），属性含 5 档偏移表 |
| `sensor.*_日常校准偏移` | 同上（日常表） |
| `switch.*_动态水温` | 动态开关；**关闭 = 冻结当前值**，不再随室外变化 |
| `switch.*_同步设备目标` | 是否下发到热水器实体 |
| `sensor.*_当前分档` | 档位 + 待切换档 + 迟滞/保持参数 + 两张完整表 |
| `sensor.*_设备下发状态` | 洗澡值 / 日常值 / 人工设定 / 已冻结 |
| `binary_sensor.*_输入有效` | 室外温度是否可用（off = 输出冻结，不下发） |

## 服务

| 服务 | 作用 |
|------|------|
| `smart_dhw.calibrate_bath` / `calibrate_daily` | 按**当前档**反推偏移并保存（不动其它档） |
| `smart_dhw.set_offset` | 直接写偏移，`band: all` 做整体平移 |
| `smart_dhw.set_band` | 手动锁定档位（忽略室外温度与迟滞） |
| `smart_dhw.reset_table` | 清除全部家庭校准偏移，回到出厂分档表 |
| `smart_dhw.recalculate` | 立即重算 |

## 校准语义

```
offset[band] = clamp(desired − trim − factory[band], min − factory[band], max − factory[band])
table[band]  = clamp(factory[band] + offset[band], min, max)
输出          = clamp(table[当前档] + trim, min, max)
```

- 存的是**逐档偏移**而不是绝对值，所以一次校准不会把 5 个档位压成同一个数。
- 未校准（偏移 0）的档位在首次校准时**跟随**同一偏移，方便一次性修正全屋管损；
  已单独校准过的档位此后不再被联动。
- 偏移窗口由上下限决定：窗口越宽，越能保留季节梯度。某档被上限截断时日志提示 `offset_clamped=True`。

## 校准时序建议

1. 洗一次澡，觉得水温不对 → 直接改 `number.*_洗澡水温`（= 校准当前档）。
2. 换季后可打开 `sensor.*_当前分档` 看 5 档偏移，用 `set_offset` + `band: all` 整体平移，再逐档微调。

## v1.2 相对 v1.1 修了什么

| # | 问题 | 修复 |
|---|------|------|
| 1 | 单偏移平移全表 + 逐格 clamp → 分档被压成常数（全部 42） | 改用**逐档偏移**，写「洗澡水温」只改当前档 |
| 2 | 室内传感器接成湿度 → 垃圾温度 | 输入统一走 `parse_temperature()`：非摄氏温度直接丢弃，配置流拒绝此类实体 |
| 3 | 传感器失效时静默返回 20 °C | 主→备→上次有效值；全部失效则**冻结输出**、不下发设备 |
| 4 | 阈值处反复跳档 | 分档迟滞（默认 1 °C）+ 换档需持续（默认 30 分钟），持久化 |
| 5 | 「动态水温」关掉后水温仍在变 | 关闭 = 数值**冻结** |
| 6 | 上下限变更会把水温向上顶 | 改上下限只**重拟合偏移**，绝不抬高水温；上限可调范围收敛到 30–50 |
| 7 | 集成与自动化双写热水器 | 只在「设备值仍等于上次下发值」时同步，人工改动一律不抢 |
| 8 | 高频状态变化触发刷新风暴 | 状态变化去抖（最小 60 s，带尾部补刷） |
| 9 | 洗澡 ≤ 日常 可能倒挂 | 强制 `日常 ≤ 洗澡 − 1 °C`（逐档） |

## 升级 / 迁移

旧存储（v1/v2 绝对分档表）在首次启动时**自动迁移**为逐档偏移，输出保持不变，无需手工处理。

## 许可

MIT
