package com.novflow.licenseadmin

/**
 * 与 novflow/shared/license/license_common.py 对齐的离线授权原语。
 */
object LicenseCrypto {
    const val PUBLIC_KEY_HEX =
        "302a300506032b65700321004615edddf20c342769637bc7b611ff0c36a9327067226ceb3d9a390552ab6e99"

    private const val DEVICE_CODE_LENGTH = 28
    private const val CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    private val K_REQ = hexToBytes("6e6f76666c6f772d61637469766174696f6e2d6b65792d7631")

    data class ProductProfile(
        val productId: String,
        val layout: String,
        val displayName: String,
    )

    val PRODUCT_DESKTOP = ProductProfile("novflow_desktop", "1", "NovFlow Desktop")
    val PRODUCT_IMAGE_DLC = ProductProfile("novflow_image_dlc", "1", "Image Engine DLC")
    val ALL_PRODUCTS = listOf(PRODUCT_DESKTOP, PRODUCT_IMAGE_DLC)

    data class NormalizeResult(val ok: Boolean, val hwId: String = "", val error: String? = null)

    fun normalizeHwId(raw: String): NormalizeResult {
        val hwId = raw.trim().lowercase().replace(Regex("[^0-9a-f]"), "")
        if (hwId.isEmpty()) return NormalizeResult(false, error = "HW_ID 不能为空")
        if (hwId.length == 16) {
            return NormalizeResult(
                false,
                error = "您输入的是 16 位短 HW_ID。请使用完整 64 位设备指纹。",
            )
        }
        if (hwId.length != 64) {
            return NormalizeResult(false, error = "HW_ID 须为 64 位十六进制（当前 ${hwId.length} 位）")
        }
        return NormalizeResult(true, hwId = hwId)
    }

    fun generateDeviceCode(profile: ProductProfile, hwId: String): String {
        val mac = javax.crypto.Mac.getInstance("HmacSHA256")
        mac.init(javax.crypto.spec.SecretKeySpec(K_REQ, "HmacSHA256"))
        mac.update(hwId.toByteArray(Charsets.UTF_8))
        mac.update(profile.productId.toByteArray(Charsets.UTF_8))
        mac.update(profile.layout.toByteArray(Charsets.UTF_8))
        val digest = mac.doFinal()
        val encoded = crockfordBase32Encode(digest).take(DEVICE_CODE_LENGTH - 1)
        val deviceCode = encoded + luhnMod32Check(encoded)
        return deviceCode.chunked(4).joinToString("-")
    }

    fun buildLicensePayload(
        profile: ProductProfile,
        hwId: String,
        licenseMode: String = "permanent",
        issuedAt: String = java.time.LocalDate.now().toString(),
        activateBefore: String? = null,
        validUntil: String? = null,
        tier: String = "full",
        batchId: String = "",
        customerRef: String = "",
    ): String {
        val json = org.json.JSONObject()
        json.put("product_id", profile.productId)
        json.put("layout", profile.layout)
        json.put("hw_id", hwId)
        json.put("license_mode", licenseMode)
        json.put("tier", tier)
        json.put("issued_at", issuedAt)
        if (licenseMode == "permanent" && !activateBefore.isNullOrBlank()) {
            json.put("activate_before", activateBefore)
        }
        if (licenseMode == "time_limited" && !validUntil.isNullOrBlank()) {
            json.put("valid_until", validUntil)
        }
        if (batchId.isNotBlank()) json.put("batch_id", batchId)
        if (customerRef.isNotBlank()) json.put("customer_ref", customerRef)
        return json.toString()
    }

    fun generateLicenseCode(payloadJson: String, privateKeyDer: ByteArray): String {
        val payloadBytes = payloadJson.toByteArray(Charsets.UTF_8)
        val privateKey =
            org.bouncycastle.crypto.util.PrivateKeyFactory.createKey(privateKeyDer) as
                org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
        val signer = org.bouncycastle.crypto.signers.Ed25519Signer()
        signer.init(true, privateKey)
        signer.update(payloadBytes, 0, payloadBytes.size)
        val sig = signer.generateSignature()
        return "v1.${b64UrlEncode(payloadBytes)}.${b64UrlEncode(sig)}"
    }

    fun validateLicenseCode(profile: ProductProfile, licenseCode: String, hwId: String): Pair<Boolean, String> {
        val code = licenseCode.trim()
        if (code.isEmpty()) return false to "激活码不能为空"
        val parts = code.split(".")
        if (parts.size != 3) return false to "激活码格式不正确（应为 v1.Payload.Signature）"
        if (parts[0] != "v1") return false to "不支持的激活码版本: ${parts[0]}"

        val payloadJson = try {
            String(b64UrlDecode(parts[1]), Charsets.UTF_8)
        } catch (e: Exception) {
            return false to "激活码载荷解析失败"
        }
        val signature = try {
            b64UrlDecode(parts[2])
        } catch (e: Exception) {
            return false to "激活码签名解析失败"
        }

        val payload = try {
            org.json.JSONObject(payloadJson)
        } catch (e: Exception) {
            return false to "激活码 JSON 无效"
        }

        if (payload.optString("product_id") != profile.productId) return false to "激活码产品不匹配"
        if (payload.optString("hw_id") != hwId) return false to "激活码与当前设备不匹配"

        val pubBytes = hexToBytes(PUBLIC_KEY_HEX)
        val publicKey =
            org.bouncycastle.crypto.util.PublicKeyFactory.createKey(pubBytes) as
                org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
        val payloadBytes = payloadJson.toByteArray(Charsets.UTF_8)
        val verifier = org.bouncycastle.crypto.signers.Ed25519Signer()
        verifier.init(false, publicKey)
        verifier.update(payloadBytes, 0, payloadBytes.size)
        if (!verifier.verifySignature(signature)) return false to "激活码签名验证失败"

        val today = java.time.LocalDate.now().toString()
        when (payload.optString("license_mode", "permanent")) {
            "permanent" -> {
                val before = payload.optString("activate_before", "")
                if (before.isNotBlank() && today > before) {
                    return false to "激活码已超过首激截止日期（$before）"
                }
            }
            "time_limited" -> {
                val until = payload.optString("valid_until", "")
                if (until.isBlank()) return false to "限时授权缺少 valid_until"
                if (today > until) return false to "激活码已过期（有效期至 $until）"
            }
        }
        return true to "验证通过（${payload.optString("license_mode")} / ${profile.displayName}）"
    }

    private fun b64UrlEncode(data: ByteArray): String =
        android.util.Base64.encodeToString(
            data,
            android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING or android.util.Base64.NO_WRAP,
        )

    private fun b64UrlDecode(text: String): ByteArray {
        val pad = "=".repeat((4 - text.length % 4) % 4)
        return android.util.Base64.decode(text + pad, android.util.Base64.URL_SAFE)
    }

    private fun hexToBytes(hex: String): ByteArray {
        val clean = hex.trim()
        return ByteArray(clean.length / 2) { i ->
            clean.substring(i * 2, i * 2 + 2).toInt(16).toByte()
        }
    }

    private fun crockfordBase32Encode(buf: ByteArray): String {
        var bits = 0
        var bitCount = 0
        val result = StringBuilder()
        for (byte in buf) {
            bits = (bits shl 8) or (byte.toInt() and 0xFF)
            bitCount += 8
            while (bitCount >= 5) {
                bitCount -= 5
                result.append(CROCKFORD[(bits shr bitCount) and 0x1F])
            }
        }
        if (bitCount > 0) {
            result.append(CROCKFORD[(bits shl (5 - bitCount)) and 0x1F])
        }
        return result.toString()
    }

    private fun luhnMod32Check(text: String): Char {
        val mapping = CROCKFORD.withIndex().associate { it.value to it.index }
        var total = 0
        var double = false
        for (ch in text.reversed()) {
            var value = mapping[ch] ?: 0
            if (double) {
                value *= 2
                if (value >= 32) value = value - 32 + 1
            }
            total += value
            double = !double
        }
        return CROCKFORD[(32 - (total % 32)) % 32]
    }
}
