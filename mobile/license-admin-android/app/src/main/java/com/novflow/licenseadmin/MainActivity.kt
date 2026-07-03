package com.novflow.licenseadmin

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import java.time.LocalDate

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = androidx.compose.ui.graphics.Color(0xFF1565C0),
                ),
            ) {
                LicenseAdminScreen()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LicenseAdminScreen() {
    var tab by remember { mutableIntStateOf(0) }
    val context = LocalContext.current
    val keyReady = remember { PrivateKeyStore.hasPrivateKey(context) }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("NovFlow 激活码管理") })
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize(),
        ) {
            Text(
                text = if (keyReady) "私钥已就绪 · 离线签发" else "私钥未打包（需 CI 构建版）",
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                color = if (keyReady) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
            )
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("生成") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("验证") })
                Tab(selected = tab == 2, onClick = { tab = 2 }, text = { Text("设备码") })
            }
            when (tab) {
                0 -> GenerateTab(keyReady)
                1 -> VerifyTab()
                2 -> DeviceCodeTab()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProductSelector(
    selected: LicenseCrypto.ProductProfile,
    onSelected: (LicenseCrypto.ProductProfile) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = !expanded },
        modifier = Modifier.fillMaxWidth(),
    ) {
        OutlinedTextField(
            value = selected.displayName,
            onValueChange = {},
            readOnly = true,
            label = { Text("产品类型") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .menuAnchor()
                .fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            LicenseCrypto.ALL_PRODUCTS.forEach { product ->
                DropdownMenuItem(
                    text = { Text("${product.displayName} (${product.productId})") },
                    onClick = {
                        onSelected(product)
                        expanded = false
                    },
                )
            }
        }
    }
}

@Composable
private fun GenerateTab(keyReady: Boolean) {
    val context = LocalContext.current
    var product by remember { mutableStateOf(LicenseCrypto.PRODUCT_DESKTOP) }
    var hwId by remember { mutableStateOf("") }
    var deviceCode by remember { mutableStateOf("") }
    var licenseMode by remember { mutableStateOf("permanent") }
    var validUntil by remember { mutableStateOf(LocalDate.now().plusYears(1).toString()) }
    var customer by remember { mutableStateOf("") }
    var batch by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ProductSelector(product) { product = it }
        OutlinedTextField(
            value = hwId,
            onValueChange = { hwId = it },
            label = { Text("HW_ID（64位）") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                val r = LicenseCrypto.normalizeHwId(hwId)
                if (!r.ok) {
                    toast(context, r.error ?: "无效")
                    return@Button
                }
                hwId = r.hwId
                deviceCode = LicenseCrypto.generateDeviceCode(product, r.hwId)
            }) { Text("计算设备码") }
        }
        OutlinedTextField(
            value = deviceCode,
            onValueChange = {},
            readOnly = true,
            label = { Text("激活设备码") },
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { licenseMode = "permanent" }, enabled = licenseMode != "permanent") {
                Text("永久")
            }
            Button(onClick = { licenseMode = "time_limited" }, enabled = licenseMode != "time_limited") {
                Text("限时")
            }
            Text("当前：$licenseMode", modifier = Modifier.align(Alignment.CenterVertically))
        }
        if (licenseMode == "time_limited") {
            OutlinedTextField(
                value = validUntil,
                onValueChange = { validUntil = it },
                label = { Text("有效期至 (YYYY-MM-DD)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
        }
        OutlinedTextField(
            value = customer,
            onValueChange = { customer = it },
            label = { Text("客户标识（可选）") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        OutlinedTextField(
            value = batch,
            onValueChange = { batch = it },
            label = { Text("批次号（可选）") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        Button(
            onClick = {
                if (!keyReady) {
                    toast(context, "当前 APK 未包含私钥")
                    return@Button
                }
                val r = LicenseCrypto.normalizeHwId(hwId)
                if (!r.ok) {
                    toast(context, r.error ?: "无效")
                    return@Button
                }
                hwId = r.hwId
                deviceCode = LicenseCrypto.generateDeviceCode(product, r.hwId)
                try {
                    val payload = LicenseCrypto.buildLicensePayload(
                        profile = product,
                        hwId = r.hwId,
                        licenseMode = licenseMode,
                        validUntil = if (licenseMode == "time_limited") validUntil else null,
                        batchId = batch.trim(),
                        customerRef = customer.trim(),
                    )
                    val key = PrivateKeyStore.loadPrivateKeyDer(context)
                    val code = LicenseCrypto.generateLicenseCode(payload, key)
                    output = buildString {
                        appendLine("=== NovFlow 激活码 ===")
                        appendLine()
                        appendLine("产品: ${product.displayName}")
                        appendLine("HW_ID: $hwId")
                        appendLine("设备码: $deviceCode")
                        appendLine("授权: $licenseMode")
                        appendLine()
                        appendLine("激活码:")
                        appendLine(code)
                    }
                } catch (e: Exception) {
                    toast(context, e.message ?: "生成失败")
                }
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("生成激活码") }

        if (output.isNotBlank()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("结果", style = MaterialTheme.typography.titleMedium)
                IconButton(onClick = { copyText(context, output) }) {
                    Icon(Icons.Default.ContentCopy, contentDescription = "复制")
                }
            }
            OutlinedTextField(
                value = output,
                onValueChange = {},
                readOnly = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(220.dp),
                textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
            )
        }
    }
}

@Composable
private fun VerifyTab() {
    val context = LocalContext.current
    var product by remember { mutableStateOf(LicenseCrypto.PRODUCT_DESKTOP) }
    var hwId by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ProductSelector(product) { product = it }
        OutlinedTextField(
            value = hwId,
            onValueChange = { hwId = it },
            label = { Text("HW_ID") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = code,
            onValueChange = { code = it },
            label = { Text("激活码") },
            modifier = Modifier
                .fillMaxWidth()
                .height(120.dp),
        )
        Button(
            onClick = {
                val r = LicenseCrypto.normalizeHwId(hwId)
                if (!r.ok) {
                    result = r.error ?: "HW_ID 无效"
                    return@Button
                }
                val (ok, msg) = LicenseCrypto.validateLicenseCode(product, code, r.hwId)
                result = if (ok) "✓ $msg" else "✗ $msg"
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("验证") }
        if (result.isNotBlank()) {
            Text(result, modifier = Modifier.padding(top = 8.dp))
        }
    }
}

@Composable
private fun DeviceCodeTab() {
    val context = LocalContext.current
    var product by remember { mutableStateOf(LicenseCrypto.PRODUCT_DESKTOP) }
    var hwId by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ProductSelector(product) { product = it }
        OutlinedTextField(
            value = hwId,
            onValueChange = { hwId = it },
            label = { Text("HW_ID") },
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = {
                val r = LicenseCrypto.normalizeHwId(hwId)
                if (!r.ok) {
                    output = r.error ?: "无效"
                    return@Button
                }
                val dc = LicenseCrypto.generateDeviceCode(product, r.hwId)
                output = "产品: ${product.displayName}\nHW_ID:\n${r.hwId}\n\n激活设备码:\n$dc"
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("生成设备码") }
        if (output.isNotBlank()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                IconButton(onClick = { copyText(context, output) }) {
                    Icon(Icons.Default.ContentCopy, contentDescription = "复制")
                }
            }
            Text(output, fontFamily = FontFamily.Monospace)
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            "提示：请让用户从客户端「授权激活」复制完整 64 位 HW_ID。Desktop 与 DLC 设备码不同。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private fun toast(context: Context, msg: String) {
    Toast.makeText(context, msg, Toast.LENGTH_LONG).show()
}

private fun copyText(context: Context, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText("license", text))
    toast(context, "已复制到剪贴板")
}
