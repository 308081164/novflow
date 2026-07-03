package com.novflow.licenseadmin

import android.content.Context
import java.io.IOException

object PrivateKeyStore {
    private const val ASSET_NAME = "issuer-private.der"

    fun loadPrivateKeyDer(context: Context): ByteArray {
        return try {
            context.assets.open(ASSET_NAME).use { it.readBytes() }
        } catch (_: IOException) {
            throw IllegalStateException(
                "未找到发行方私钥（assets/$ASSET_NAME）。\n" +
                    "请使用 GitHub Actions 注入密钥后安装的正式 APK。",
            )
        }
    }

    fun hasPrivateKey(context: Context): Boolean = try {
        context.assets.open(ASSET_NAME).close()
        true
    } catch (_: IOException) {
        false
    }
}
