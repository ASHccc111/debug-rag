---
source_key: demo-camera-card
title: 调试页相机状态卡片的接入与验证
app_snapshot: demo-v1
data_kind: simulated
feature_status: delivered
updated_at: 2026-10-25
external_processing_allowed: true
---
# 调试页相机状态卡片

本文为模拟说明。适用场景为把相机状态放在 DemoDebug 调试页内，不能直接用来解释跨页面悬浮层。

## 接入顺序

1. 检查业务快照为 demo-v1，演示相机模拟器已初始化。
2. 在调试页注册“相机状态”卡片入口。
3. 进入页面时绑定状态观察者，把 camera_id、phase、permission 和 observed_at 显示在卡片中。
4. 状态变化时更新现有卡片，不重复创建入口或观察者。
5. 离开调试页时解除订阅；重新进入时主动读取最新快照。

## 如何验证

让模拟器依次进入 closed、opening、previewing，确认卡片按顺序更新，且 observed_at 跟随新快照变化。把模拟权限切到 denied，确认权限提示变化，不把 denied 显示成预览成功。

离开调试页再返回，应看到当前快照，而不是离开前缓存的数据。连续进入退出三次，订阅计数每次恢复到进入前的值；只有停留在调试页期间存在这张卡片的订阅。

## 常见问题

如果状态停止变化，先查看模拟器是否继续产生快照，再检查页面进入时是否绑定观察者。若每个事件显示多次，检查是否重复注册。以上步骤只针对演示状态展示，不包含实际相机硬件故障诊断。
