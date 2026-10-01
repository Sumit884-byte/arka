# 边缘设备模式

Arka 可以为笔记本电脑、Raspberry Pi 级别设备以及电池供电的机器
运行受限的本地配置：

```bash
arka edge status
arka edge recommend
```

该配置优先使用紧凑的量化本地模型，并推荐设置
`ARKA_MODEL_POLICY=local-only`，从而使提示词不会回退到托管服务。
