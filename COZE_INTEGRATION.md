# 扣子平台集成方案

本文档说明如何将司南嵌入到扣子（Coze）平台，实现自然语言驱动的硬件交互。

## 一、整体架构

```
用户 ←对话→ 扣子 Agent ←插件调用→ 司南 API Server ←串口/TCP/WiFi→ ESP32 硬件
                                    (ASGI, port 5000)
```

## 二、扣子平台配置步骤

### 步骤 1：部署司南 API Server

将 `agent/api.py` 部署为可公网访问的 HTTP 服务。选项：

- **云服务器**：任意 VPS，先安装 API 运行依赖 `pip install -e ".[api]"`，再运行 `uvicorn agent.api:app --host 0.0.0.0 --port 5000`
- **内网穿透**：ngrok / frp 将本地 5000 端口暴露到公网
- **容器化**：Docker + 任意容器平台

设置环境变量：
```bash
SINAN_API_KEY=your-secret-key   # 必设，保护 API 不被滥用
```

### 步骤 2：注册扣子插件

1. 登录 [扣子开发平台](https://www.coze.cn)
2. 进入「插件」→「创建插件」
3. 选择「云端插件」→「通过 OpenAPI Schema 创建」
4. 上传 `coze-plugin-openapi.json` 文件
5. 将 `servers[0].url` 替换为实际的 API 地址
6. 在「鉴权」中选择「API Key」，填入 `X-API-Key` 头的值

### 步骤 3：创建智能体

1. 进入「智能体」→「创建智能体」
2. 名称：**司南 — 嵌入式 AI 硬件搭档**
3. 描述：面向嵌入式开发者的智能硬件助手，用自然语言操控开发板

### 步骤 4：配置 Agent Prompt

将以下内容粘贴到智能体的「人设与回复逻辑」中：

```
# 角色

你是**司南 (Sinán)**，一个专业的嵌入式智能体。你的用户是嵌入式开发者，
你用自然语言帮他们操控硬件——扫描设备、编译固件、烧录、读取传感器、查询芯片手册。

# 核心能力

1. **串口扫描**：用户说"扫描串口"或"看看有哪些设备"时，调用 scanSerial
2. **串口监听**：用户说"看看串口输出"或"监听日志"时，调用 serialMonitor
3. **传感器读取**：用户说"读取传感器"或"采集数据"时，调用 sensorRead
4. **固件编译**：用户说"编译"或"build"时，调用 buildFirmware
5. **固件烧录**：用户说"烧录"或"flash"时，调用 flashFirmware（需确认！）
6. **知识检索**：用户问芯片/协议/传感器参数时，调用 knowledgeSearch
7. **板卡查询**：用户说"有哪些板卡"时，调用 boardList；查看详情时调用 boardProfile
8. **设备桥接**：用户说"读取设备状态"或"向设备发送命令"时，调用 deviceBridge

# 安全规则

- **烧录操作**是高危操作，执行前必须向用户确认芯片型号和固件路径
- **编译操作**是中危操作，需确认项目路径
- 串口监听有 30 秒时间上限，传感器采集有 30 秒上限
- 不编造芯片参数，不确定时调用 knowledgeSearch 查询

# 回复风格

- 简洁专业，直接给结果
- 标注信息来源：[数据手册] / [实测] / [知识库]
- 操作结果附关键数据（端口列表、编译错误摘要、传感器读数统计）
- 危险操作前主动提醒风险
```

### 步骤 5：绑定插件

在智能体配置页的「插件」区域，添加步骤 2 中创建的司南插件。

### 步骤 6：导入知识库

1. 将 `knowledge/` 目录下的 `.md` / `.yaml` 文件整理为文本文件
2. 在扣子「知识库」中创建新知识库，上传这些文件
3. 在智能体中关联此知识库

重点导入内容：
- `knowledge/mcu/` — MCU 数据手册摘要
- `knowledge/protocol/` — I2C/SPI/UART 协议规格
- `knowledge/sensor/` — 传感器参数
- `knowledge/error_code/` — 常见错误码

### 步骤 7：创建工作流

在扣子「工作流」中创建以下工作流，展示扣子使用深度：

#### 工作流 1：硬件黄金路径（scan → build → flash → verify）

```
开始
  → scanSerial（扫描设备）
  → 判断：是否检测到目标板卡？
    → 否：返回"未检测到设备，请检查连接"
    → 是：buildFirmware（编译固件）
      → 判断：编译是否成功？
        → 否：返回编译错误
        → 是：flashFirmware（烧录固件，需人工确认节点）
          → serialMonitor（验证烧录结果）
          → 返回完整报告
```

#### 工作流 2：传感器诊断（scan → read → analyze）

```
开始
  → scanSerial（扫描设备）
  → sensorRead（采集传感器数据）
  → LLM 节点（分析数据异常）
  → knowledgeSearch（查错误码/解决方案）
  → 返回诊断报告
```

### 步骤 8：配置数据库

在扣子「数据库」中创建表，映射司南 L1 记忆：

| 表名 | 字段 | 用途 |
|------|------|------|
| board_sessions | board_id, port, baudrate, last_connected | 板卡连接记录 |
| pitfall_log | board_id, issue, solution, timestamp | 踩坑记录 |
| firmware_history | chip, firmware_path, build_time, status | 固件编译历史 |

## 三、ESP32 固件侧对接

ESP32 端需要运行固件，实现与司南的双向通信：

### 通信协议选择

| 方式 | 适用场景 | 复杂度 |
|------|----------|--------|
| **WiFi + HTTP** | ESP32 作为 HTTP 服务器，司南通过 device_bridge 调用 | 中 |
| **WiFi + MQTT** | 双向推送，适合实时性要求高 | 中 |
| **串口 + JSONL** | 简单直接，通过 serial_monitor 和 sensor_read 交互 | 低 |

### 推荐方案：WiFi + HTTP

ESP32 运行 HTTP Server，暴露 REST 端点：
- `GET /status` — 设备状态（GPIO、传感器读数、WiFi 信息）
- `POST /gpio` — 控制 GPIO（读/写）
- `POST /action` — 执行复杂动作（如舵机控制、步进电机）

司南通过 `device_bridge` 插件向 ESP32 发送 JSONL-RPC 请求。

### ESP32 固件框架（ESP-IDF）

```c
// main/main.c — 最小双向交互框架
#include <esp_http_server.h>
#include <esp_wifi.h>
#include <cjson/cJSON.h>

// GET /status — 硬件状态上报
esp_err_t status_handler(httpd_req_t *req) {
    cJSON *resp = cJSON_CreateObject();
    cJSON_AddStringToObject(resp, "chip", "ESP32-S3");
    cJSON_AddNumberToObject(resp, "free_heap", esp_get_free_heap_size());
    cJSON_AddNumberToObject(resp, "gpio2_level", gpio_get_level(2));
    // ... 传感器数据
    char *json_str = cJSON_PrintUnformatted(resp);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, json_str, strlen(json_str));
    free(json_str);
    cJSON_Delete(resp);
    return ESP_OK;
}

// POST /action — AI 下发指令
esp_err_t action_handler(httpd_req_t *req) {
    char buf[256];
    httpd_req_recv(req, buf, sizeof(buf));
    cJSON *cmd = cJSON_Parse(buf);
    const char *action = cJSON_GetStringValue(cJSON_GetObjectItem(cmd, "action"));
    // 执行动作...
    cJSON_Delete(cmd);
    httpd_resp_sendstr(req, "{\"ok\":true}");
    return ESP_OK;
}
```

## 四、一等奖评审维度对照

| 评审维度 | 权重 | 司南覆盖 | 需额外补齐 |
|----------|------|----------|-----------|
| AI与硬件结合度 | 30% | 插件+工作流+知识库全链路 | ESP32 双向交互固件 |
| 乐鑫芯片技术实现 | 25% | ESP32 平台抽象已有 | 低功耗优化、实际烧录验证 |
| 场景价值 | 20% | 嵌入式生产力工具 | 商业化论述 |
| 创新性 | 15% | AI 驱动硬件全流程（行业首创） | 与传统工具的差异化叙事 |
| 完成度 | 10% | 614 测试+API层+OpenAPI spec | 真机演示视频 |

## 五、提交清单

- [ ] 产品说明文档（按比赛模板）
- [ ] 1-5 分钟演示视频（社媒发布 + 指定标签）
- [ ] 扣子 Agent 可在线访问
- [ ] ESP32 硬件实物可交互
