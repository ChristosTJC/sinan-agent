# Bluetooth Low Energy (BLE) 协议栈

## 概述

Bluetooth Low Energy（BLE，蓝牙低功耗）是 Bluetooth 4.0 引入的低功耗无线通信协议，专为物联网设备设计。

## 协议栈架构

```text
┌─────────────────────────────────┐
│      应用层 (Application)        │
├─────────────────────────────────┤
│      GAP (通用访问配置文件)      │
│      GATT (通用属性配置文件)     │
├─────────────────────────────────┤
│      ATT (属性协议)              │
│      SMP (安全管理协议)          │
├─────────────────────────────────┤
│      L2CAP (逻辑链路控制)        │
├─────────────────────────────────┤
│      HCI (主机控制接口)          │
├─────────────────────────────────┤
│      Link Layer (链路层)         │
├─────────────────────────────────┤
│      Physical Layer (物理层)     │
└─────────────────────────────────┘
```

## GAP (Generic Access Profile)

### 角色
- **Central**: 中心设备（扫描、连接）
- **Peripheral**: 外设（广播、被连接）
- **Broadcaster**: 广播者（仅广播）
- **Observer**: 观察者（仅扫描）

### 广播类型
- **ADV_IND**: 可连接、可扫描
- **ADV_DIRECT_IND**: 定向广播
- **ADV_NONCONN_IND**: 不可连接
- **ADV_SCAN_IND**: 可扫描、不可连接

### 连接参数
- **Connection Interval**: 7.5ms - 4s
- **Slave Latency**: 0 - 499
- **Supervision Timeout**: 100ms - 32s

## GATT (Generic Attribute Profile)

### 层次结构
```text
Profile
  └─ Service (服务)
       └─ Characteristic (特征)
            ├─ Value (值)
            └─ Descriptor (描述符)
```

### 特征属性
- **Read**: 可读
- **Write**: 可写（需要响应）
- **Write Without Response**: 可写（无需响应）
- **Notify**: 通知（无需确认）
- **Indicate**: 指示（需要确认）

### 标准服务
- **0x1800**: Generic Access
- **0x1801**: Generic Attribute
- **0x180A**: Device Information
- **0x180D**: Heart Rate
- **0x180F**: Battery Service

## ATT (Attribute Protocol)

### 操作类型
- **Read**: 读取属性
- **Write**: 写入属性
- **Notify**: 服务器主动通知
- **Indicate**: 服务器主动指示（需确认）

### MTU (Maximum Transmission Unit)
- 默认: 23 字节
- 最大: 512 字节（BLE 5.2）
- 协商: ATT_MTU_REQ / ATT_MTU_RSP

## SMP (Security Manager Protocol)

### 配对方式
- **Just Works**: 无需用户交互
- **Passkey Entry**: 输入密钥
- **Numeric Comparison**: 数字比较
- **Out of Band**: 带外配对

### 安全等级
- **Level 1**: 无安全
- **Level 2**: 未认证配对
- **Level 3**: 认证配对
- **Level 4**: 认证 LE Secure Connections

## BLE 5.x 新特性

### BLE 5.0
- **2M PHY**: 2 Mbps 物理层（提升吞吐量）
- **Coded PHY**: 编码物理层（提升距离）
- **Advertising Extensions**: 扩展广播（最大 255 字节）

### BLE 5.1
- **Direction Finding**: 方向查找（AoA/AoD）

### BLE 5.2
- **LE Audio**: 低功耗音频
- **EATT**: 增强 ATT（多通道）

## Nordic SoftDevice

### SoftDevice 版本
- **S132**: nRF52 系列（Central + Peripheral）
- **S140**: nRF52840（支持 BLE 5）
- **S113**: nRF5340 网络核

### API 层次
```text
应用代码
    ↓
SoftDevice API (sd_ble_*)
    ↓
SoftDevice (协议栈)
    ↓
硬件 (RADIO, TIMER)
```

## 开发示例

### 初始化 BLE 栈
```c
// 启用 SoftDevice
sd_softdevice_enable(&clock_config, fault_handler);

// 配置 BLE 栈
ble_cfg_t ble_cfg;
sd_ble_cfg_set(BLE_CONN_CFG_GAP, &ble_cfg, ram_start);

// 启用 BLE 栈
sd_ble_enable(&ram_start);
```

### 开始广播
```c
ble_gap_adv_params_t adv_params = {
    .type = BLE_GAP_ADV_TYPE_ADV_IND,
    .interval = 160,  // 100ms
    .timeout = 0,     // 无超时
};

sd_ble_gap_adv_start(&adv_params, APP_BLE_CONN_CFG_TAG);
```

### 添加服务和特征
```c
// 添加服务
ble_uuid_t service_uuid = {.uuid = 0x1234, .type = BLE_UUID_TYPE_VENDOR_BEGIN};
sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY, &service_uuid, &service_handle);

// 添加特征
ble_gatts_char_md_t char_md = {
    .char_props.read = 1,
    .char_props.notify = 1,
};
sd_ble_gatts_characteristic_add(service_handle, &char_md, &attr_char_value, &char_handle);
```

## 功耗优化

### 连接间隔优化
- 短间隔（7.5-50ms）: 低延迟，高功耗
- 长间隔（100-1000ms）: 高延迟，低功耗

### Slave Latency
- 允许外设跳过连接事件
- 降低功耗，增加延迟

### 广播间隔优化
- 快速广播（20-100ms）: 快速发现，高功耗
- 慢速广播（1-10s）: 慢速发现，低功耗

## 参考资料

- [Bluetooth Core Specification](https://www.bluetooth.com/specifications/specs/)
- [Nordic nRF Connect SDK BLE Guide](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/ug_ble.html)
- [BLE Developer's Handbook](https://www.bluetooth.com/bluetooth-resources/)
