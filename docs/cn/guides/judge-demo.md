# 评审就绪的演示包

创建一个不含密钥的评估包：

```bash
arka judge-demo init ./judge-demo
arka judge-demo check ./judge-demo
```

该包包含一个清单（manifest）、合成数据政策、安全的环境变量
示例，以及评审可以在现有 Arka 安装上运行的命令。
它不会重新构建项目，也不包含生产环境凭据。

支持的平台包括 macOS 12+、使用 glibc 的 Linux，以及通过 WSL2 运行的 Windows。
生成的 README 包含针对每个平台的虚拟环境创建、激活以及 `pip`
安装说明。
