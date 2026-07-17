# NovFlow 品牌资产（Brand Assets）

面向宣发、安装包与桌面端的官方视觉素材。源图为用户选定的横向 logo（图标 + NovFlow 字标 + tagline）。

## 文件清单

| 文件 | 尺寸 | 用途 |
|------|------|------|
| `logo.png` | 1024×682 | 横向品牌标识（图标 + NovFlow + AI NOVEL WRITING PLATFORM） |
| `icon.png` | 1024×1024 | 方形应用主图标（钢笔-N 丝带，无文字） |
| `icon.ico` | 16 / 32 / 48 / 64 / 128 / 256 | Windows 安装包 / 快捷方式 / Electron 窗口与 exe（ICO 最大 256） |
| `icons/icon-16.png` … `icon-512.png` | 16, 32, 48, 64, 128, 256, 512 | 分尺寸 PNG（调试 / 平台适配） |
| `generate_brand_assets.py` | — | 从参考图裁切图标并同步到各端 |

同步副本（由脚本写入，勿手改后忘记回写 master）：

| 路径 | 内容 |
|------|------|
| `frontend/public/favicon.png` | 32×32 标签页图标 |
| `frontend/public/favicon.ico` | 多尺寸 ICO（浏览器兼容） |
| `frontend/public/icon.png` | 1024×1024（应用内 `BrandMark`、apple-touch-icon） |
| `frontend/public/logo.png` | 横向 logo（登录页等） |
| `desktop/electron/icon.png` | Electron 非 Windows 窗口图标 |
| `desktop/electron/icon.ico` | Electron Windows 窗口 / electron-builder |
| `desktop/electron/logo.png` | 启动页 `loading.html` |

安装程序：`installer/novflow.iss` → `SetupIconFile=..\assets\brand\icon.ico`。

## 设计理念

- **符号**：抽象字母 **N**，融合钢笔笔尖与丝带流动，呼应「写作」与「Flow」。
- **气质**：文学感 + 现代 AI 工具感，专业、克制。
- **可读性**：方形图标无文字，小尺寸（16–32px）仍可辨认。

## 色彩规范

| 角色 | 色值 | 说明 |
|------|------|------|
| 主背景 Navy | `#0B1B3A` | 深靛蓝，专业稳重 |
| 辅背景 Indigo | `#1A2744` | 渐变/卡片底 |
| 流动强调 Cyan | `#22D3EE` | 叙事之流、科技感 |
| 文学强调 Gold | `#F5C542` | 笔尖高光、创作灵感 |
| 字标白 | `#F8FAFC` | 横向 logo 文字 |

渐变方向：Cyan → Gold（左冷右暖），象征从构思到成文的流动。

## 宣发尺寸建议

| 场景 | 素材 | 建议尺寸 |
|------|------|----------|
| 社交头像 / 应用商店 | `icon.png` | 512×512 或 1024×1024 |
| 微信/微博封面、Banner | `logo.png` | 宽 ≥ 1024px，可居中裁切 |
| 官网 / 应用 Header | `icon.png` + 字标，或 `logo.png` | 高度 32–64px |
| 启动页 / Splash | `logo.png` | 按画布居中 |
| Windows 任务栏 / 桌面 | `icon.ico` | 含 16/32/48/256/512 |
| 安装程序 Setup | `icon.ico` | Inno Setup `SetupIconFile` |
| 浏览器标签 | `favicon.png` / `favicon.ico` | 32×32 显示即可 |

## 使用注意

1. **方形图标不要叠字**：`icon.png` 仅图形；需要品牌名时用 `logo.png`。
2. **深色背景优先**：素材为深色底；浅色背景上请加圆角与细描边（见 `BrandMark` / Header）。
3. **勿拉伸变形**：等比缩放；横向 logo 勿压扁。
4. **最小安全边距**：图标四周保留约 10% 内边距，避免贴边裁切。

## 重新生成

更新参考图后，编辑 `generate_brand_assets.py` 中的 `REF` 路径与 `ICON_CROP`（如需），然后：

```powershell
# 需 Pillow：python -m pip install Pillow
python assets/brand/generate_brand_assets.py
```

脚本会：

1. 保存完整横向图为 `logo.png`
2. 裁切左侧圆角方形图标 → `icon.png`（1024）与 `icons/icon-*.png`
3. 生成多尺寸 `icon.ico`
4. 同步到 `frontend/public/` 与 `desktop/electron/`

或仅从已有 `icon.png` 重建 ICO：

```powershell
python -c "
from PIL import Image
from pathlib import Path
src = Path(r'assets/brand/icon.png')
img = Image.open(src).convert('RGBA')
sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
img.save(src.with_name('icon.ico'), format='ICO', sizes=sizes)
"
```

## 各端如何生效

| 端 | 生效方式 |
|----|----------|
| **Web / Docker** | 静态资源在 `frontend/public/`；重新 `npm run build`（或 Docker 重建 frontend 镜像）后标签页与应用内 logo 更新 |
| **桌面 Electron** | `desktop/electron/icon.*` + `logo.png`；开发态直接生效；打包需 `package-desktop.ps1` / electron-builder |
| **安装包** | `assets/brand/icon.ico` 由 Inno Setup 读取；需重新编译 `installer/novflow.iss` 才更新 Setup 图标 |
