# NovFlow Image Engine（Stub）

开发/集成测试用占位引擎，**不含** diffusers / torch。未安装真实模型时返回彩色占位 PNG。

## 启动

```powershell
cd image-engine
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
python -m image_engine
```

或：

```powershell
.\start.ps1
```

服务监听 **http://127.0.0.1:17860**，API 前缀 `/v1`。

## 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/health` | 健康检查 |
| GET | `/v1/capabilities` | 能力声明 |
| POST | `/v1/generate` | 文生图（占位 PNG） |
| POST | `/v1/generate/test` | 64×64 自检 |

## 与主程序联调

1. 启动本 stub
2. NovFlow 设置 → 本地生图扩展（DLC）→ 确认 EULA → 后端选「本地 DLC」→ 测试连接
3. 在书籍/章节中触发生图

正式 DLC 安装包见 [docs/LOCAL_IMAGE_DLC.md](../docs/LOCAL_IMAGE_DLC.md)。
