# NovFlow 激活码管理工具

## 私钥

- 路径：`tools/.issuer-private.der`（Ed25519 PKCS#8 DER，**勿提交 git**）
- 公钥 hex 已写入 `shared/license/license_keys.py` 与 Android `LicenseCrypto.kt`

## CLI

```powershell
py -3 tools\generate_license.py generate --product desktop --hw-id <64位HW_ID>
py -3 tools\generate_license.py generate --product dlc --hw-id <64位HW_ID>
py -3 tools\generate_license.py verify --product desktop --hw-id <HW_ID> --code "v1...."
py -3 tools\generate_license.py device-code --product dlc --hw-id <HW_ID>
```

## Android APK

见 `mobile/license-admin-android/README.md`
