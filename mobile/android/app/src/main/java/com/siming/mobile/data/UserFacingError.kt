package com.siming.mobile.data

import com.siming.mobile.data.network.GatewayHttpException
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

internal fun Throwable.toUserFacingMessage(): String = when (this) {
    is GatewayHttpException -> message.ifBlank { "Gateway 请求没有完成，请稍后重试" }
    is UnknownHostException -> "找不到 Gateway，请检查地址或网络后重试"
    is ConnectException -> "无法连接 Gateway，请确认网络和 Gateway 运行状态后重试"
    is SocketTimeoutException -> "连接 Gateway 超时，请检查网络后重试"
    is IOException -> "与 Gateway 通信失败，请检查网络后重试"
    else -> message?.takeIf(String::isNotBlank) ?: "操作没有完成，请重试"
}
