package com.siming.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.lifecycle.lifecycleScope
import com.google.zxing.client.android.Intents
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.siming.mobile.ui.MainViewModel
import com.siming.mobile.ui.PortraitCaptureActivity
import com.siming.mobile.ui.SimingApp
import com.siming.mobile.ui.SimingTheme
import java.io.InputStreamReader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    private val qrScanner = registerForActivityResult(ScanContract()) { result ->
        result.contents?.let(viewModel::acceptPairingQr)
    }

    private var importCallback: ((String, String) -> Unit)? = null
    private val textPicker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        val callback = importCallback
        importCallback = null
        if (uri == null || callback == null) return@registerForActivityResult
        lifecycleScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val name = contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                        val index = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                        if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
                    } ?: "导入作品.txt"
                    val text = contentResolver.openInputStream(uri)?.use { input ->
                        val reader = InputStreamReader(input, Charsets.UTF_8)
                        val buffer = CharArray(8_192)
                        val builder = StringBuilder()
                        while (true) {
                            val count = reader.read(buffer)
                            if (count < 0) break
                            builder.append(buffer, 0, count)
                            require(builder.length <= 20_000_000) { "单个导入文件不能超过 2000 万字符" }
                        }
                        builder.toString()
                    } ?: error("无法读取选择的文件")
                    name to text
                }
            }.onSuccess { (name, text) -> callback(name, text) }
                .onFailure { viewModel.reportError(it.message ?: "无法读取选择的文件") }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SimingTheme {
                SimingApp(
                    viewModel = viewModel,
                    onScanQr = {
                        qrScanner.launch(
                            ScanOptions()
                                .setCaptureActivity(PortraitCaptureActivity::class.java)
                                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                                .setPrompt("扫描电脑上司命生成的一次性配对二维码")
                                .setBeepEnabled(false)
                                .setOrientationLocked(true)
                                .addExtra(Intents.Scan.SCAN_TYPE, Intents.Scan.MIXED_SCAN),
                        )
                    },
                    onPickText = { callback ->
                        importCallback = callback
                        textPicker.launch("text/*")
                    },
                )
            }
        }
    }
}
