# NovFlow 激活码管理 Android APK

离线 Ed25519 签发，与 `shared/license/` 及 `tools/generate_license.py` 算法一致。

**一个 APK** 可为以下两种产品签发激活码（在 UI 中选择产品类型）：

- NovFlow Desktop (`novflow_desktop`)
- NovFlow 本地生图引擎 (`novflow_image_dlc`)

## GitHub Actions 构建

1. 在仓库 Settings → Secrets 配置 `NOVFLOW_ISSUER_PRIVATE_PKCS8_HEX`（`tools/.issuer-private.der` 的 hex）
2. 推送 tag `license-admin-v*` 或在 Actions 中手动运行 **Build License Admin APK**
3. 从 Release 下载 `NovFlow激活码管理.apk`

导出私钥 hex（PowerShell）：

```powershell
[BitConverter]::ToString([IO.File]::ReadAllBytes("tools\.issuer-private.der")).Replace("-","").ToLower()
```

## 本地构建（需 Android SDK）

```bash
# 将私钥放入 app/src/main/assets/issuer-private.der
cd mobile/license-admin-android
./gradlew assembleRelease
```

## 安全

APK 内含发行方私钥，**仅限管理员本人使用，切勿公开分发**。
