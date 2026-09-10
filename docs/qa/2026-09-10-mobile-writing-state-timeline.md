# 手机草稿状态与助手消息顺序修复

## 问题与修复

- 连接 Gateway 时，待保存草稿接口返回 null 后，仓库层此前还会取项目包旧草稿作为 fallback；界面恢复和写作完成后的刷新也会保留旧值。现在接口的空结果直接清空待保存状态，网络失败保留当前状态并报告错误，二者不再混淆。
- 草稿刷新使用请求代次和读取前的草稿值校验。保存、丢弃、作者编辑和新草稿事件使旧读取失效；切换项目后迟到的读取也不能回写。任务错误、取消只更新正在生成的草稿，不改动其他待保存草稿的状态。
- 手机独立模式的界面、每个模型步骤和写章执行共用同一草稿查询，读取本机日志与项目副本。新章草稿对应的正式章节已经存在时释放旧草稿；已保存、丢弃、失效及带 saved_chapter_id 的项目包草稿不再出现。已有章节的修订候选仍与正式正文分离。
- 独立模式每步提供 chapter_writing_state。正文新增或变化会在本地保存事务中设 cataloging_required=true；仅改标题保留原状态，空正文不形成建档阻塞。该标志不进入作者的 API 写入参数，服务器仍自行决定权威建档状态。生成前、生成结果登记前检查待建档状态，正式章节的迟到写入不会被生成结果覆盖。
- PC 与手机从同一 Python 常量导出实时状态说明。历史中的“尚未保存/建档中”不能覆盖本步真实状态；缺少 cataloging_required 的旧资料明确显示为状态未知，不能假定完成。工具类别、用户意图、实体选择继续由当前模型按现有契约决定。
- 会话消息保留 sequence_no；手机本机日志和 Gateway 对话共用显示规则。历史工具记录归属原回复并默认折叠，不再复制到列表底部。重复发送相同文字依靠不同回合 ID 分开展示。切换会话的迟到读取不能覆盖新回合；流式工具记录增长不再反复强制滚动。
- 建档结束后的副本刷新错误不再被静默吞掉，避免刷新失败仍显示“手机已刷新”。

## 验证结果

- Android 全量 JVM 单元测试：292 项通过，0 失败、0 错误、0 跳过，包含新增 10 项状态生命周期、草稿异步读取和时间线回归。
- 后端：test_chapter_writing_state.py、test_mobile_prompt_contract.py、test_ai_writer.py 共 60 项通过；手机能力对齐、提示词预算和共享质量提示词另 7 项通过。API 与 CLI 路径的模拟模型回归通过，未调用真实模型。
- `:app:testDebugUnitTest :app:assembleDebug --no-daemon` 成功，日志 `.build/mobile-state-build.log`。APK 中的提示词资产与当前源码字节一致，APK v2 签名验证通过，正常仓库配置下的 diff whitespace 检查通过。
- 先前的 Gradle `Unable to establish loopback connection` 已定位为 Windows JDK Unix domain socket 临时目录问题；本次进程使用短目录 `-Djdk.net.unixdomain.tmpdir=D:/AI/simingdevelop/.build/uds` 后测试和构建恢复。未修改用户全局 Java 配置。
- 未连接 Android 真机或模拟器，未声称完成真机交互验收。未改动作者的生产正文、草稿、建档任务和历史消息。

## 平台差异

手机独立执行完整章节建档是现有能力缺口，详见 `docs/mobile-pc-parity.md` 的 chapter.cataloging。本次修复独立运行时对已保存、已建档和待重新建档的判断，没有增加独立建档执行器。界面明确说明当前版本执行建档需要 Gateway；待建档或状态未知时不会绕过门槛续写。

## 测试包

- `release/mobile-workspace-state-20260910/Siming-mobile-test.apk`
- 版本：3.3.13-debug；应用 ID：com.siming.mobile.debug；最低 Android 8.0。
- 大小：22,350,539 字节。
- SHA256：`cf93dece474a2a60d6ad88cb1ca6fbc3fb368abe4c567e31414f9264f0ace2d9`。
- 当前环境没有正式发布签名配置，提供 Android 调试签名测试包。该应用 ID 使用独立数据空间，第一次使用需要配对 Gateway 或导入项目、配置手机 API。
