"""Task-local authoring; never imported by the RAG application."""
import json, hashlib
from pathlib import Path
from collections import Counter, defaultdict

OUT=Path(json.loads((Path(__file__).parent/'paths.json').read_text(encoding='utf-8'))['output'])
BLOCKS={x['block_id']:x for x in map(json.loads,(OUT/'source_blocks.jsonl').read_text(encoding='utf-8').splitlines())}
cases=[]; families=[]

def src(d,n,q=None):
    b=BLOCKS[f'DOC-{d:02d}-B{n:06d}'];t=b['text'];q=q or t
    assert q in t,(b['block_id'],q)
    return (b,q)

def point(text,*sources,literals=(),critical=True,alternatives=False):
    return dict(text=text,sources=sources,literals=literals,critical=critical,alternatives=alternatives)

def add(cat,topic,family,question,points,claim,reason,claim_refs=()):
    evidence=[];ps=[];seen={}
    for p in points:
        refs=[]
        for b,q in p['sources']:
            k=(b['block_id'],q)
            if k not in seen:
                g=f'G{len(evidence)+1}';seen[k]=g;s=b['text'].index(q)
                evidence.append(dict(evidence_id=g,role='support',doc_id=b['doc_id'],source_sha256=b['source_sha256'],block_id=b['block_id'],char_start=s,char_end=s+len(q),quote=q))
            refs.append(seen[k])
        ps.append(dict(point_id=f'P{len(ps)+1}',text=p['text'],critical=p['critical'],required_literals=list(p['literals']),support_sets=[[r] for r in refs] if p['alternatives'] else [refs]))
    c=dict(case_id=f'DBG-EVAL-{len(cases)+1:04d}',split='dev',family_id=family,category=cat,topic=topic,question=question,expected_status='answered',reference_answer='\n'.join(p['text'] for p in ps),retrieval_scored=True,required_points=ps,forbidden_claims=[dict(claim=claim,severity='critical',reason=reason,evidence_ids=[f'G{r}' for r in claim_refs])],evidence=evidence,response_requirements=[],absence_check=None,clarification=None,review=dict(machine_checked=False,human_status='pending',approved_by=None,approved_at=None,notes=[]))
    cases.append(c);families.append(dict(family_id=family,case_id=c['case_id'],main_intent=question,grouping_reason='主要用户目标：'+question+' 决定性事实与条件：'+'；'.join(p['text'] for p in ps)+'。只选本族一个代表；共享背景原文不自动构成同族。'))

F='fact';O='operation';C='cross_document';S='status'
ov='overview_initialization';ph='phone_performance';ca='camera';rg='registry_state';fl='field_selection_overlay';hs='hotspot_detection';ex='export_share';hb='host_build_maintenance';pv='phase2_verification'

add(F,ov,'spi-missing-implementation','接入方只依赖 debug_api、没有打包 SPI 实现时，调用 DebugFeature 能否自动静默跳过？',[
 point('不能假定静默跳过：DebugFeature.service 使用 loadNotNull 获取 IDebugService，依赖声明、SPI 注册产物与实现打包需要形成完整链路。',src(2,6),literals=['DebugFeature.service','loadNotNull','IDebugService'])],
 '只依赖 API 时门面会自动忽略调用。','文档明确不支持该假设。',[1])
add(F,ph,'cpu-normalized-process','Debug 手机 CPU 百分比的计算口径是什么，能把它当作整机 CPU 占用吗？',[
 point('分子是 Process.getElapsedCpuTime 增量，分母为经过时间乘可用 CPU 核数，再乘 100 并限制在 0 到 100。',src(5,8),literals=['Process.getElapsedCpuTime']),
 point('这是按核心数归一化的进程指标，不能当作整机 CPU 占用。',src(5,8),src(5,9))],
 '显示值是全设备所有进程的 CPU 总占用。','资料将其限定为进程指标。',[1,2])
add(F,ph,'pss-heap-zero','手机性能中 PSS 能由 Java Heap 和 Native Heap 相加得到吗，PSS 显示 0 应怎样理解？',[
 point('这些字段不满足简单相加等于 PSS 的关系。',src(5,12,'这些字段不满足简单相加等于 PSS 的关系。')),
 point('PSS 采集失败时当前以零构造快照；显示 0 前应核实采集成功与否，不能直接解释为未占内存。',src(5,12,'PSS 读取失败时当前实现以零参与构造快照，这与明确的空值状态不同；解读为零内存使用之前应核实采集是否成功。'))],
 'PSS 为 0 必然说明应用完全没有内存占用。','采集失败也会生成零。',[2])
add(F,ph,'phone-source-field-identity','接入手机通用性能字段时，怎样区分手机设备 ID、来源 ID 和字段键，数值需要先拼接单位吗？',[
 point('手机设备 ID 为 sdk.phone，来源 ID 为 sdk.phone.performance；字段以 sourceId 与 fieldId 共同识别。',src(6,5),literals=['sdk.phone','sdk.phone.performance','sourceId','fieldId']),
 point('数值字段传原始数值，不先拼成带单位的字符串。',src(6,9))],
 '字段更新可以把数字先拼为带 MB 的字符串。','文档要求保持原始数值。',[2])
add(F,ca,'formatter-percent-range','相机详情格式化电量时，负数和超过 100 的值各怎样显示？',[
 point('formatPercent 对非负数添加 %；负数显示 --。',src(29,662),src(29,663),literals=['formatPercent','%','--']),
 point('当前 formatPercent 不把大于 100 的数限制到 100。',src(29,662),src(29,663))],
 '超过 100 的电量显示值会自动截断为 100%。','PDF 的实际规则明确不限制大于 100。',[1,2])
add(F,ca,'invalid-dev-default-battery','相机 Dev 数据无效时，能把底层默认电量 100 作为有效电量展示吗？',[
 point('不能。应按 pktVersion != -1 判断 Dev 数据有效性；无效时 devStatus 整体为空，避免把底层默认电量 100 当作真实状态。',src(9,5),src(9,6),literals=['pktVersion','devStatus'])],
 '默认电量 100 足以证明相机确实满电。','资料要求有效性判断并说明默认值风险。',[1,2])
add(F,rg,'state-incremental-null','StateStore 更新一张只包含部分字段的 map 时，遗漏字段、显式 null 和空 map 分别代表什么？',[
 point('updateFields 是增量合并，未出现的字段保留原值。',src(13,5),literals=['updateFields']),
 point('显式 null 删除对应字段。',src(13,5),literals=['null']),
 point('空 map 直接返回；删除后会清理空的嵌套 map。',src(13,6))],
 '没有出现在本次 map 的字段都会自动删除。','增量合并保留省略字段。',[1])
add(F,rg,'state-copy-depth','调用 StateStore.getFields 得到 map 后，修改其中可变对象是否一定不会影响缓存？',[
 point('getFields 返回 map 的复制，不能把这个保证扩展为对内部 Any 对象的深复制；调用方不应依赖它隔离可变对象修改。',src(13,8),literals=['getFields','Any'])],
 'getFields 对所有内部对象执行深复制。','资料只保证 map 复制。',[1])
add(F,fl,'selection-null-empty','浮窗字段选择中的 null 和空列表有什么区别，用户取消所有选择后会自动恢复默认项吗？',[
 point('null 表示尚未配置，走默认字段；空列表表示用户主动不选任何项。',src(14,8),literals=['null']),
 point('主动全不选不应被自动恢复默认项。',src(14,8))],
 '空列表与未配置相同，都会恢复默认项。','资料区分这两种配置语义。',[1])
add(F,fl,'overlay-device-disambiguation','同一来源绑定了多台相机时，悬浮窗会怎样决定读取哪台设备？',[
 point('相机来源除来源绑定关系外，还要求设备 ID 与 currentCameraDeviceId 一致。',src(15,11),literals=['currentCameraDeviceId']),
 point('无法唯一确定设备时不读值，不随机取第一台。',src(15,12,'无法唯一确定设备时不读取值，避免随机取第一台相机。'))],
 '多台相机时总是读取绑定列表第一台。','文档明确避免这种选择。',[2])
add(F,hs,'hotspot-meaning-coverage','热区红框是按什么条件选出 View 的，它能证明实际点击必然生效吗？',[
 point('候选为可见且可点击、可长按或属于滚动容器的 View，并排除包装层自身。',src(16,8)),
 point('红框来自 View 坐标转换与绘制，不等于已精确扣除遮挡或证明业务点击回调成功。',src(16,9),src(16,18))],
 '有红框就证明业务 onClick 已成功执行。','资料明确限制该显示的意义。',[3])
add(F,ex,'app-log-file-selection','现场导出勾选 App 日志后，系统按什么规则选择日志文件？',[
 point('从 DirectoryPath.getLogPath 扫描可读普通文件，选 lastModified 最大的一份。',src(17,8),literals=['DirectoryPath.getLogPath','lastModified']),
 point('这是文件选择规则，不代表按日志记录时间逐行筛选了用户指定区间。',src(17,8))],
 '导出会按日志行时间提取任意指定区间。','文件修改时间不等于逐行的时间过滤。',[1])
add(F,ca,'camera-top-identity-copy','相机详情顶部显示的身份尾号如何产生，复制全部文本也只含尾号吗？',[
 point('顶部优先取 SN，缺失时取 uniKey，再显示后四位。',src(9,12,'详情顶部身份优先取 SN，缺失时取 uniKey，再显示后四位。'),literals=['SN','uniKey']),
 point('复制全部文本包含完整 SN 与 uniKey，顶部尾号不等于复制内容全面脱敏。',src(9,12,'复制全部文本会包含完整 SN 与 uniKey；顶部只显示尾号不等于复制和导出已经全面脱敏。'),literals=['SN','uniKey'])],
 '全部复制也只会保留身份后四位。','文档明确复制内容包含完整身份字段。',[2])
add(F,ov,'architecture-parallel-consumers','当前架构中旧快照链路和新通用字段链路分别服务哪些展示，为什么不能直接把它们混成同一套设备值？',[
 point('旧路径以 CameraDebugSnapshot 和 PerformanceSnapshot 为中心，供主面板、相机详情和导出读取。',src(24,11),literals=['CameraDebugSnapshot','PerformanceSnapshot']),
 point('新路径 PhonePerformanceSource 经接收器更新 StateStore，供浮窗通用存储读取。',src(24,12),literals=['PhonePerformanceSource','StateStore']),
 point('通用存储能容纳多设备不等于旧相机入口已迁移；页面不能混用不同设备缓存。',src(24,13),src(24,14))],
 '主面板、详情、导出和浮窗已经统一读取同一套多设备相机数据。','PDF 区分并行路径及迁移边界。',[3,4])
add(F,rg,'registry-state-receiver-division','设备字段链路里的 Registry、StateStore 和 Receiver 分别负责什么？',[
 point('Registry 负责定义与绑定，StateStore 负责实时值，Receiver 组合两者。',src(25,9,'Registry 负'),src(25,10),literals=['Registry','StateStore','Receiver'])],
 'StateStore 单独保存并管理全部来源定义与绑定。','PDF 把这些职责分别交给 Registry 与 StateStore。',[1,2])

add(O,ov,'runtime-release-order','手动释放 Debug SDK 时，Runtime 中各类资源应按什么顺序收尾？',[
 point('先停止 activeDataProvider。',src(3,14),literals=['activeDataProvider']),
 point('随后释放悬浮窗，再移除性能转发监听并释放性能采集器。',src(3,14)),
 point('然后注销相机事件、释放热区，最后丢弃注册、状态和配置组件引用；SDK.release 还复位自身标记。',src(3,14),literals=['SDK.release'])],
 '只关闭面板就等于停止 Provider 并释放全部全局采集资源。','资料规定显式 Runtime/SDK 释放链路。',[])
add(O,ov,'network-environment-switch','测试人员在主面板切换测试网络环境后，还需要做什么才能按文档完成操作？',[
 point('开关保存 BaseUrlManager.NET_DEBUG_MODE_KEY 的布尔值，默认值来自 BuildEnvProxy.isDebug。',src(4,8),literals=['BaseUrlManager.NET_DEBUG_MODE_KEY','BuildEnvProxy.isDebug']),
 point('保存后需要重启应用；不能仅凭开关立即变化断言所有现有客户端已切换网络环境。',src(4,8),src(4,9))],
 '勾选开关后所有已创建网络客户端立即完成切换。','资料要求重启，且 UI 状态不能证明客户端环境。',[1,2])
add(O,ph,'performance-foreground-lifecycle','按当前手机性能采集机制，应用前后台切换时如何启动和停止采样，采样耗时用什么时间基准？',[
 point('以 started Activity 计数管理：从 0 到 1 启动，全部停止时取消采样。',src(5,5)),
 point('Handler 约每 1000 毫秒调度，实际间隔用 elapsedRealtime 计算，不能将每次间隔视作严格一秒。',src(5,6),literals=['Handler','1000','elapsedRealtime'])],
 '无 Activity 在前台时仍按固定一秒无条件持续采样。','资料的前台计数与实际间隔规则不支持该说法。',[1,2])
add(O,ca,'camera-name-late-callback','相机快照没有名称时如何查询并避免重复请求，设备切换后的旧回调如何处理？',[
 point('通过 DeviceCore.queryDeviceName 单独查询，以集合限制同一 uniKey 的重复请求；名称不属于 0x070 大包字段。',src(7,11),literals=['DeviceCore.queryDeviceName','uniKey','0x070']),
 point('查询失败或暂未刷新时，10000 毫秒后解除请求限制。',src(7,12)),
 point('回调先检查 monitor 仍注册且当前快照 uniKey 相同，避免把前一台设备名称写入新设备快照。',src(7,12),literals=['uniKey'])],
 '名称回调可以不核对设备身份直接覆盖当前快照。','文档要求检查注册状态与同一 uniKey。',[2])
add(O,ca,'camera-detail-visible-subscriptions','相机详情页进入和离开可见状态时应怎样订阅数据，离开页面会关闭全局相机监控吗？',[
 point('详情页在 onStart 订阅，在 onStop 取消页面订阅。',src(11,5),literals=['onStart','onStop']),
 point('页面退出不负责停止全局相机事件监控，不能用页面退出来代替全局资源释放。',src(11,5))],
 '相机详情 onStop 会自动注销整个应用的全局相机监控。','页面订阅与全局监控生命周期不同。',[1])
add(O,rg,'receiver-registration-preconditions','一个新设备来源第一次向 DebugDataReceiverImpl 更新字段前，必须满足哪些注册和绑定条件？',[
 point('先注册设备与来源；设备和来源之间无资料要求的先后依赖。',src(12,5),src(12,6)),
 point('来源存在后才能 registerFields；设备与来源都存在后才能 bindSource。',src(12,6),literals=['registerFields','bindSource']),
 point('updateFields 前来源须已绑定该设备；未绑定会返回，不会隐式创建设备。',src(12,8),literals=['updateFields'])],
 '首次 updateFields 会自动建立来源、设备和绑定。','文档明确未绑定直接返回。',[3])
add(O,rg,'source-unregister-global-cleanup','一个来源已经停止服务全部设备，注销来源应清哪些值和注册关系，注销单个设备能替代吗？',[
 point('unregisterSource 清所有设备该来源的实时值，再删除来源字段与绑定。',src(12,11),literals=['unregisterSource']),
 point('注销某设备只处理该设备，不等于删除全局来源；其他设备可能仍使用同一来源。',src(12,12))],
 '注销任意一个设备就会删除所有设备共用的来源。','文档明确区分设备与全局来源。',[2])
add(O,fl,'selection-group-over-limit','浮窗勾选整个字段分组后会超过数量上限，选择器应怎么处理，能否自动只取前几项？',[
 point('先形成整组选择候选并检查上限；浮窗上限为 8。',src(14,5),src(14,13)),
 point('整组候选超限就拒绝本次变化并保留原选择，不能自动截取前几项。',src(14,13))],
 '超限时选择器会取分组前 8 项并替换原选择。','文档要求整次拒绝且保持原结果。',[2])
add(O,fl,'floating-drag-position','当前浮窗怎样拖动并保存位置，Activity 暂停后会怎样处理浮窗？',[
 point('从文本拖动区域用 raw 坐标差移动并做边界限制，按钮区域不作为同样的拖动入口。',src(15,8)),
 point('UP 或 CANCEL 时将 lastX、lastY 保存在内存。',src(15,9),literals=['UP','CANCEL','lastX','lastY']),
 point('Activity 暂停时 detach 浮窗并关闭弹窗，但保留启用状态以便后续恢复。',src(15,6))],
 '暂停 Activity 会永久清掉浮窗启用状态和全部位置配置。','资料区分 detach 与启用状态保留。',[3])
add(O,hs,'hotspot-enable-draw-listener','在业务 Activity 开启热区后，内容层如何包装，滚动监听如何随包装层挂载和卸载管理？',[
 point('Activity resumed 时检查内容首个子 View，已有 HighlightFrameLayout 则复用，否则包装内容。',src(16,5),literals=['HighlightFrameLayout']),
 point('包装层 attach 时注册滚动监听、detach 时注销；开启检测时触发更新。',src(16,12),literals=['attach','detach'])],
 '每次 Activity 恢复都必须叠加一个新的包装层。','文档要求检查并复用已有包装。',[1])
add(O,ex,'zip-failure-retention','ZIP 写入失败与成功时各如何清理文件，用户取消系统分享是否有立即删除产物的步骤？',[
 point('写入失败时尝试删除未完成 ZIP 并重新抛出异常，删除返回值没有完整清理报告。',src(17,15)),
 point('成功后按最后修改时间保留最近五个 ZIP，清理更旧 ZIP。',src(17,15)),
 point('系统分享取消没有专门的立即删除回调，不能套用旧模拟资料中的取消即删除规则。',src(17,16))],
 '任何分享取消都会立即删除所有本次产物。','真实项目资料明确没有这个专门回调。',[2])
add(O,ex,'share-content-uri-setup','把导出的 ZIP 交给系统分享时，URI、authority、Intent 和文件目录必须怎样对应？',[
 point('用 FileProvider.getUriForFile 创建 content URI，authority 为当前 packageName 加 .debug.fileprovider，并与变体 Manifest 的 applicationId 对应。',src(18,11),literals=['FileProvider.getUriForFile','.debug.fileprovider','applicationId']),
 point('Intent 使用 ACTION_SEND、application/zip、EXTRA_STREAM、ClipData 和 FLAG_GRANT_READ_URI_PERMISSION，只授予对应 URI 的临时读取权限。',src(18,12),literals=['ACTION_SEND','application/zip','EXTRA_STREAM','ClipData','FLAG_GRANT_READ_URI_PERMISSION']),
 point('真实导出文件须落在 debug_file_paths.xml 声明的 external-files-path 或 files-path 根下 OBSBOT/DebugExport 相对范围内。',src(18,14),literals=['debug_file_paths.xml','OBSBOT/DebugExport'])],
 '授予分享 URI 权限后接收方可任意读取应用目录。','文档把授权范围限定在对应 URI。',[2])
add(O,ex,'export-success-chain','按当前现场导出流程，读取页面选项之后，到启动系统选择器之前有哪些必要阶段和失败出口？',[
 point('先校验空选择；空选择或选中 App 日志却无日志文件时停止。',src(26,23)),
 point('到 IO 读取所选日志与状态快照，再写 ZIP。',src(26,18),src(26,19)),
 point('ZIP 写入失败时尝试删除未完成文件并返回失败。',src(26,23)),
 point('成功后清理并保留最近五份，返回 ZIP；分享端先创建 FileProvider content URI，再 ACTION_SEND 授权并启动 chooser。',src(26,20),src(26,21),src(26,27),src(26,28),src(26,29),literals=['FileProvider','ACTION_SEND'])],
 '尚未生成 ZIP 时就应先把文件交给接收 App。','PDF 成功流程有先生成产物再创建分享链路的明确顺序。',[])
add(O,hb,'diagnose-missing-display-layers','相机详情或浮窗显示缺失值时，维护者应按哪些层排查，能否直接认定硬件故障？',[
 point('先区分无设备、无事件、无有效分组、无注册、无绑定、无实时值、设备选择不唯一和格式类型错误；不能先认定硬件坏了。',src(20,11)),
 point('相机检查 uniKey、状态查询、Mapper 的 Dev 判定、最近快照时间和页面监听。',src(20,12),literals=['uniKey','Mapper']),
 point('通用字段检查 Registry 与 StateStore；浮窗还检查启用状态、当前 Activity 和当前相机 ID。这些检查没有资料规定的唯一总顺序。',src(20,12),literals=['Registry','StateStore','Activity'])],
 '显示缺失值足以唯一归因相机硬件故障。','资料列出多层可能性并要求按证据排查。',[1])
add(O,hb,'build-variant-verification-order','准备核验 Debug 编译隔离时，模块依赖、实际构建和产物检查应怎样安排，CI 记录应包含什么？',[
 point('先检查模块依赖约束，再按实际任务名构建允许变体，并检查依赖和 APK 内容。',src(21,14)),
 point('发布包不能只查类，还要检查 Manifest、资源、SPI、依赖与初始化入口。',src(21,9),literals=['Manifest','SPI']),
 point('CI 证据要绑定分支、提交、变体、任务及产物；这些核验步骤本身不等于已经执行成功。',src(21,15))],
 '只查发布包没有某个 Debug 类即可证明隔离验收完成。','资料还要求组件、资源、SPI、依赖和构建证据。',[2,3])

add(C,ca,'stale-camera-after-event-error','相机事件处理报错后界面仍有旧数据，应如何解释该数据与主面板的大包更新提示？',[
 point('事件异常会被捕获，旧快照可能仍在，不能把有值当作刚收到新的状态。',src(7,17)),
 point('主面板用当前时间与 receivedAtMillis 比较，超过 2000 毫秒按更新过期提示解释；这个判定不等于已证明设备断开。',src(4,17),literals=['receivedAtMillis','2000'])],
 '界面还有旧值就证明大包持续正常刷新。','事件异常可保留旧快照，仍需看时间。',[1])
add(C,ca,'voice-connection-derived-display','接入相机详情的“语音设备已连接”显示时，Formatter 读什么属性，这个属性是怎样得到的？',[
 point('详情表达式为 formatBoolean(status.voiceDeviceAttached)，标签是 Connect / 语音设备已连接。',src(29,273),src(29,274),literals=['formatBoolean(status.voiceDeviceAttached)']),
 point('voiceDeviceAttached 是三个音频接入标记的逻辑或，属于计算字段，不是额外收到的协议字段。',src(10,9,'voiceDeviceAttached 是三个音频接入标记的逻辑或，属于计算字段，不是额外接收的协议字段。'),literals=['voiceDeviceAttached'])],
 '该显示对应一个独立下发的 voiceDeviceAttached 协议字段。','文档说明它是逻辑或计算属性。',[3])
add(C,ov,'open-page-context-and-listeners','从非 Activity 的 Context 打开 Debug 主页面时，入口标记和页面可见期监听应怎样配合？',[
 point('打开页面的 Intent 需要 FLAG_ACTIVITY_NEW_TASK。',src(2,8),literals=['FLAG_ACTIVITY_NEW_TASK']),
 point('主页面在 onStart 加入性能、相机、热区、浮窗开关和字段选择监听，onStop 移除并关闭弹窗。',src(3,11),literals=['onStart','onStop'])],
 '给 Intent 加标记就可以省略页面退出时的监听清理。','页面可见期监听另有独立生命周期要求。',[2])
add(C,ex,'zip-identity-privacy-cross','转发相机现场 ZIP 前，文件名里的身份尾号与 camera_status.txt 中的身份内容各是什么，能据文件名判断已全面脱敏吗？',[
 point('ZIP 文件名包含手机型号、手机 DID 后四位和时间片段。',src(17,12),literals=['DID']),
 point('相机状态使用格式化文本放入 camera_status.txt；formatCopyText 的全部复制内容包含完整 SN 和 uniKey。',src(17,11),src(8,14),src(11,14),src(9,12),literals=['camera_status.txt','formatCopyText','SN','uniKey']),
 point('因此不能用文件名的尾号规则证明内容已全面脱敏，应审查完整身份字段。',src(17,19))],
 'ZIP 名称只含 DID 尾号，因此相机正文也一定只含身份尾号。','文件名与相机格式化正文是不同的数据范围。',[1,2,3])
add(C,ca,'phone-camera-temperature-units','做手机与相机电池温度对比时，两类值能否直接按相同摄氏度口径计算温差？',[
 point('手机电池温度来自广播 EXTRA_TEMPERATURE 除以 10，单位为摄氏度，缺失时 null。',src(5,15),literals=['EXTRA_TEMPERATURE','null']),
 point('相机电池温度当前按 getter 整数复制，单位与缩放需协议确认，不能直接假定摄氏度并计算同口径温差。',src(9,14),src(9,15))],
 '相机 temperature 的整数天然与手机摄氏度是相同单位和缩放。','资料明确禁止猜测相机单位。',[3])
add(C,rg,'port-camera-pc-count-source','要把相机详情的 PC 连接数接入通用字段链路，旧页取值表达式是什么，第一次接收新值前要满足哪些注册绑定条件？',[
 point('旧页 router.pc_count 对应 PC 连接数，表达式为 formatInt(status.pcCount)。',src(29,319),src(29,320),src(29,321),literals=['router.pc_count','formatInt(status.pcCount)']),
 point('注册字段前来源须存在，绑定前设备和来源须存在；字段 ID 在来源内唯一。',src(12,6)),
 point('接收 updateFields 前该来源须已绑定目标设备，否则更新直接返回。',src(12,8),literals=['updateFields']),
 point('旧详情显示 ID 不自动等于 Registry 的 sourceId、fieldId，需要明确适配身份。',src(29,6),src(29,7),literals=['sourceId','fieldId'])],
 '把旧详情 ID 直接发送给接收器就会自动注册并绑定相机。','PDF 区分身份，接收契约要求显式注册绑定。',[4,5,6])
add(C,rg,'registry-subscription-initial-ui-thread','新接入页面订阅 Registry 后要显示已有定义并响应后续变化，首次读取和 View 更新线程应怎样处理？',[
 point('Registry 注册监听不立即回放，页面需要主动读取当前注册信息。',src(3,12)),
 point('Registry 回调运行在更新发起线程，不保证主线程；直接在回调操作 View 有线程风险，应转交主线程。',src(12,14),src(12,15),literals=['Registry','View'])],
 'Registry 注册监听一定会在主线程立即回放已有全部定义。','回放语义与通知线程均不支持这个假设。',[1,2])
add(C,hs,'hotspot-runtime-release-tree','集成 SDK 释放时，热区清理在 Runtime 的哪个阶段，是否必须把业务内容从包装层拆出来？',[
 point('Runtime 在注销相机事件后释放热区，再丢弃注册、状态和配置引用。',src(3,14)),
 point('热区 release 在主线程关闭检测、注销生命周期并清理引用，但不拆除既有 View 包装树。',src(16,14),literals=['release','View'])],
 '释放热区必然将业务 View 从包装层还原到原树结构。','热区文档明确不执行拆树操作。',[2])
add(C,ph,'fps-history-record-design','二期要导出手机 FPS 时间曲线，采样值应沿用什么口径，历史记录还需增加什么信息并以什么格式导出？',[
 point('沿用采样期间 Choreographer 回调次数乘 1000 除以实际毫秒数的应用帧回调频率，不能改称相机或编码器帧率。',src(5,14),literals=['Choreographer']),
 point('二期设计要求保存带时间戳的长时间性能采样记录，并导出 CSV；这是设计要求。',src(23,8),literals=['CSV'])],
 '把 App 帧回调频率写入 CSV 就能称为相机传感器帧率。','资料限定 FPS 指标的语义，CSV 不改变口径。',[1])
add(C,ca,'camera-field-extension-expand-state','给旧相机详情新增字段时，数据映射应沿哪些层修改，刷新列表又如何保持用户已展开的分组？',[
 point('从底层 getter 到 Snapshot、Mapper 再到 Formatter 的稳定 ID、标签和值逐层维护。',src(20,8),literals=['Snapshot','Mapper','Formatter']),
 point('详情按分组保留展开状态；媒体和设备组默认展开，其他默认折叠，刷新不应重置用户选择。',src(11,9))],
 '每次快照刷新都应将全部分组重置为默认展开状态。','详情文档要求刷新保留展开状态。',[2])

add(S,ov,'initialization-static-contract-status','在资料声明的基线版本，能把 Debug 初始化接口描述为已对齐且编译验证通过吗？',[
 point('不能。IDebugService 有单参数和带 dependencies 的双参数 initialize，Impl 只实现单参数且调用 Runtime 单参数，但 Runtime 要求双参数。',src(2,11),literals=['IDebugService','initialize','dependencies']),
 point('API 引用了位于 Impl 的 DebugDependencies，构成类型边界问题；资料只是静态发现，未执行编译，不能报告编译通过。',src(2,12),literals=['DebugDependencies'])],
 '资料已证明初始化接口对齐并编译通过。','资料明确静态不一致且没有本轮编译结论。',[1,2])
add(S,ca,'multi-device-foundation-not-migrated','在本套基线资料中，通用设备状态存储已出现，是否就表示相机主面板和详情完成多设备迁移？',[
 point('不能。当前 CameraDebugMonitor 仍持有单份 latestSnapshot，供相机主面板、详情和导出读取。',src(1,9),literals=['CameraDebugMonitor','latestSnapshot']),
 point('通用注册与状态结构是基础能力，手机来源已接通不能证明相机入口完成迁移。',src(1,8),src(1,9))],
 '通用存储存在即可宣布所有相机页面已按设备隔离。','资料区分基础结构和相机消费者迁移。',[1,2])
add(S,fl,'field-target-config-maturity','基线文档里存在主面板、浮窗、详情字段配置目标枚举，能否据此认为所有页面已统一配置且持久化？',[
 point('不能。MAIN_PANEL、FLOATING_WINDOW、DETAIL_PAGE 的限制定义不等于全部页面已接通；表格说明主要已接通的是浮窗。',src(14,24),src(14,25),src(14,26),src(14,27),src(14,28),src(14,29),src(14,30),src(14,31),src(14,32),literals=['MAIN_PANEL','FLOATING_WINDOW','DETAIL_PAGE']),
 point('当前配置保存在内存，不是 SharedPreferences 持久化。',src(14,9),literals=['SharedPreferences'])],
 '枚举存在证明三个页面均已支持统一配置并跨进程重启保存。','文档区分枚举、接通页面与内存存储。',[3,6,9,10])
add(S,fl,'floating-fold-snap-not-current','以资料的当前实现为限，浮窗拖动松手后是否已支持折叠和自动吸边？',[
 point('当前仅在 UP/CANCEL 保存内存位置，没有折叠或吸边完整实现。',src(15,9),literals=['UP','CANCEL']),
 point('不能把当前自由拖动和位置恢复描述为已完成折叠吸边。',src(15,9))],
 '基线浮窗已经具备折叠状态和每次松手自动吸边。','当前行为文档明确排除了该实现。',[1])
add(S,pv,'advanced-debug-placeholder','资料所述当前主面板中的连接诊断和固件通信入口，能否用于执行完整诊断和指令 Mock？',[
 point('不能把入口当作完整能力：当前为开发中占位，点击显示开发中。',src(1,5),src(1,37),src(1,38),src(1,39)),
 point('当前能力边界不支持据此宣称诊断和通信 Mock 已实现。',src(1,37),src(1,38),src(1,39))],
 '显示入口就证明已支持固件 Mock 和连接时间线。','入口状态明确为占位。',[2,3,4])
add(S,ex,'export-current-target-matrix','在本套资料的基线版本，现场日志导出能提供什么，时间区间、相机日志和性能历史分别处于什么阶段？',[
 point('当前列是最新 App 日志与快照 ZIP。',src(28,37),src(28,38)),
 point('二期目标列是时间区间、相机日志和性能历史，不能把同一行目标列当成当前实现。',src(28,37),src(28,39))],
 '对照表证明当前已完成区间日志、相机日志和性能历史导出。','这是把目标列误读为当前列。',[2,3])
add(S,hb,'sdk-independence-and-start-status','按基线宿主适配文档，能宣称通用 SDK 已完全摆脱 Live 依赖并已在 Start 验证了吗？',[
 point('不能。存在 Provider 契约，但未在核对范围发现明确实现 DebugDataProvider 的 Live Adapter，旧相机链路仍直接依赖宿主组件。',src(19,8),src(19,9),literals=['DebugDataProvider']),
 point('UI/Domain/Data 是逻辑分层，不等于已经拆成三个独立 AAR。',src(19,12),literals=['UI','Domain','Data','AAR']),
 point('Start 仓库与接入验证没有在本次资料核对中完成，跨 App 结论需要独立构建与设备证据。',src(19,15),src(19,18),literals=['Start'])],
 '本套资料已经证明 Live、Start 均完成独立 SDK 接入验收。','文档明确接入和核验范围边界。',[1,2,4,5])
add(S,hb,'flavor-config-versus-proof','基线 Gradle 已配置 Flavor 隔离后，是否可以把 Release 不含 Debug 实现和 Jenkins 通过都写成验收结果？',[
 point('不能。允许变体为 withDebugDebug、withDebugStaging、withoutDebugRelease，这是配置证据。',src(21,5),src(21,6),literals=['withDebugDebug','withDebugStaging','withoutDebugRelease']),
 point('还需真实依赖图、实际产物内容与 Jenkins 构建证据；资料中的核验要求不证明本轮已通过。',src(21,9),src(21,15),literals=['Jenkins'])],
 'Flavor 配置存在即可宣称 Release APK 与 Jenkins 已经验证通过。','配置、产物与构建结果是不同证据层次。',[3,4])
add(S,pv,'verification-plan-no-results','基线资料中写有 Debug 多设备与效率验收方法，能否引用为已完成测试和效率提升的证明？',[
 point('不能。验证文档是待执行方法与记录要求，不是已执行结果。',src(22,2)),
 point('效率需固定任务、基线和样本数测量，当前表中效率项目为未测量，不能编造提升比例。',src(22,18),src(22,38),src(22,39),src(22,40))],
 '验收方法已写出即可报告效率提升百分比。','文档明确未测量并要求真实基线。',[2,3,4,5])
add(S,pv,'phase2-export-policy-design','阅读二期目标架构时，如何描述统一导出对多来源数据和部分失败的设计，哪些接口细节仍不能当作现有实现？',[
 point('这是二期设计：统一任务汇集区间 App 日志、固件支持的相机日志、性能记录及最新应用设备快照。',src(27,2),src(27,3),src(27,9)),
 point('各来源返回成功、缺失或失败，再按明确策略决定是否生成产物；不能据此杜撰已落地的部分失败策略。',src(27,10)),
 point('运行参数来源、相机日志接口、Mock 注入点、权限与跨 App 资源依赖仍待确认，不编造接口签名或协议编号。',src(27,14),src(27,15),literals=['Mock'])],
 '目标图已给出并实现全部相机日志协议编号和部分失败策略。','文档将这些依赖明确列为待确认。',[5,6])

def boundary(status,topic,family,q,answer,requirements,claim,reason,evidence=(),absence=None,clarification=None):
    ev=[]
    for b,quote in evidence:
        st=b['text'].index(quote);ev.append(dict(evidence_id=f'G{len(ev)+1}',role='disambiguation' if status=='clarify' else 'scope',doc_id=b['doc_id'],source_sha256=b['source_sha256'],block_id=b['block_id'],char_start=st,char_end=st+len(quote),quote=quote))
    c=dict(case_id=f'DBG-EVAL-{len(cases)+1:04d}',split='dev',family_id=family,category='boundary',topic=topic,question=q,expected_status=status,reference_answer=answer,retrieval_scored=False,required_points=[],forbidden_claims=[dict(claim=claim,severity='critical',reason=reason,evidence_ids=[])],evidence=ev,response_requirements=requirements,absence_check=absence,clarification=clarification,review=dict(machine_checked=False,human_status='pending',approved_by=None,approved_at=None,notes=[]))
    cases.append(c);families.append(dict(family_id=family,case_id=c['case_id'],main_intent=q,grouping_reason='独立边界目标：'+q+'；决定性条件为 '+status+'：'+answer+'。本族只选一个代表，不与同义改写拆分。'))

def absent(topic,fam,q,missing,docs,summary,sources):
    boundary('insufficient_evidence',topic,fam,q,'这批资料不足以确定'+missing+'；需要补充对应实测记录或已确认接口资料。',['明确指出资料缺少'+missing,'不能把缺失记录说成该能力在真实业务中不存在。'],'给出未经记录的'+missing+'作为确定事实。','所选范围内没有支持该具体结论的资料。',sources,dict(missing_information=missing,checked_doc_ids=[f'DOC-{d:02d}' for d in docs],check_summary='已通读固定30份资料的主要正文、表格及图示文字，并重点核对'+summary+'。只说明本套资料不足，不外推其他版本或外部资料。'))

absent(ph,'missing-measured-monitor-overhead','开启手机性能悬浮窗后，CPU 平均额外开销和 P95 帧耗时分别是多少？','开启浮窗的 CPU 额外开销与 P95 帧耗时实测值',[5,15,22],'手机采样机制、浮窗行为和验证要求；这些给出采样口径或待测方法，没有开关对照试验数值',[src(5,17),src(22,18)])
absent(ex,'missing-camera-log-endpoint','二期获取相机日志应调用哪个已确认的固件协议编号，请给出请求字段定义？','已确认的相机日志协议编号与请求字段',[17,23,27],'当前导出、二期目标和架构；相机状态不是相机固件日志，接口仍待确认',[src(23,8),src(27,14),src(27,15)])
absent(hb,'missing-start-device-run-results','Start 接入 Debug SDK 后，在哪些真实设备型号上完成了哪几项运行测试？','Start 的真实设备型号和逐项运行结果',[19,21,22,28],'宿主接入边界、构建核验、验收记录和迁移对照；Start 独立验证没有本套结果记录',[src(19,15),src(22,35),src(22,36),src(22,37)])
absent(pv,'missing-mock-rule-wire-contract','二期指令 Mock 的具体规则 JSON 字段和超时响应错误码是什么？','Mock 规则 JSON 字段和超时响应错误码',[1,23,27],'占位入口和高级调试设计；只说明规则匹配及真实链路边界，未给规则结构和错误码约定',[src(23,12),src(27,14),src(27,15)])

for fam,topic,q,ans in [
 ('outside-cooking',ov,'请给我一份四人份红烧肉的详细菜谱。','这个请求属于烹饪，与 Debug 项目文档助手范围无关。可以引导使用通用烹饪助手。'),
 ('outside-wedding-poem',ov,'帮我写一首婚礼祝福诗。','这个请求属于祝福诗创作，与 Debug 项目文档助手范围无关。可以引导使用通用写作助手。'),
 ('outside-travel-plan',ov,'请规划一条三天的巴黎旅游路线。','这个请求属于旅行规划，与 Debug 项目文档助手范围无关。可以引导使用旅行规划服务。')]:
    boundary('out_of_scope',topic,fam,q,ans,['说明该目标超出 Debug 项目文档助手范围，可作简短引导。'],'将本套 Debug 文档声称为可支持该外部任务的业务依据。','请求的目标明确不属于本知识助手职责。')

boundary('clarify',fl,'clarify-target-field-limit','我要配置主面板或悬浮窗的展示字段，这次最多可以选多少个？','先确认这次要配置主面板还是悬浮窗，再给对应上限。',['只追问本次配置目标是主面板还是悬浮窗。'],'未确认目标就一律回答上限为 8。','两种目标的限制不同。',[src(14,5)],clarification=dict(missing_slot='本次配置目标页面',acceptable_question_intent='确认目标是 MAIN_PANEL 还是 FLOATING_WINDOW。',example_question='这次要配置主面板，还是悬浮窗？',interpretations=[dict(condition='目标为主面板 MAIN_PANEL',answer_difference='最大 12 个字段。',evidence_ids=['G1']),dict(condition='目标为悬浮窗 FLOATING_WINDOW',answer_difference='最大 8 个字段。',evidence_ids=['G1'])]))
boundary('clarify',rg,'clarify-source-clear-scope','要清理一个调试数据来源，应该调用哪个清理接口？','先确认要仅清实时值并保留来源，还是连来源定义和绑定一起注销。',['只追问是否保留来源定义和绑定。'],'未确认清理范围就直接要求全局注销来源。','仅清缓存与注销来源对定义和绑定影响不同。',[src(13,14),src(12,11)],clarification=dict(missing_slot='清理是否保留来源注册及绑定',acceptable_question_intent='确认仅清实时值，还是注销来源。',example_question='要保留该来源的定义和绑定，只清实时值，还是把来源一起注销？',interpretations=[dict(condition='保留来源定义和绑定，只清该来源实时值',answer_difference='使用 StateStore.clearSource；它不处理 Registry 注销。',evidence_ids=['G1']),dict(condition='注销来源及其字段和绑定',answer_difference='使用接收器 unregisterSource，清所有设备该来源值并删除定义和绑定。',evidence_ids=['G2'])]))
boundary('clarify',rg,'clarify-listener-replay-kind','新页面订阅 Debug 数据监听后，要不要主动读取当前数据才能显示首屏？','先确认订阅的是性能/相机快照监听，还是 Registry 注册信息监听。',['只追问本次订阅的监听类型。'],'未确认监听类型就断言所有监听都会立即回放。','两类监听的回放语义不同。',[src(3,12,'性能和相机监听会回放最新快照；'),src(3,12,'Registry 的监听注册不立即回放，订阅者需要读取当前注册信息。')],clarification=dict(missing_slot='订阅的监听类型',acceptable_question_intent='确认性能/相机快照监听，还是 Registry 注册信息监听。',example_question='这里订阅的是性能或相机快照，还是 Registry 的注册信息变化？',interpretations=[dict(condition='性能或相机快照监听',answer_difference='监听会回放最新快照。',evidence_ids=['G1']),dict(condition='Registry 注册信息监听',answer_difference='注册不立即回放，首屏需要主动读取当前注册信息。',evidence_ids=['G2'])]))

# Split the field-limit disambiguation into distinct original slices, with no invented text.
c=cases[57];assert c['family_id']=='clarify-target-field-limit'
# Use the actual native table cells to separate the two possible answers.
c['evidence']=[]
for n in [24,25,27,28]:
    b=BLOCKS[f'DOC-14-B{n:06d}'];c['evidence'].append(dict(evidence_id=f'G{len(c["evidence"])+1}',role='disambiguation',doc_id=b['doc_id'],source_sha256=b['source_sha256'],block_id=b['block_id'],char_start=0,char_end=len(b['text']),quote=b['text']))
c['clarification']['interpretations'][0]['evidence_ids']=['G1','G2'];c['clarification']['interpretations'][1]['evidence_ids']=['G3','G4']

SEED=20261104
DEV={'fact':10,'operation':10,'cross_document':6,'status':7,'boundary:insufficient_evidence':3,'boundary:out_of_scope':2,'boundary:clarify':2}
strata=defaultdict(list)
for c in cases:
    key=c['category'] if c['category']!='boundary' else 'boundary:'+c['expected_status'];strata[key].append(c)
allocations=[]
for key,rows in sorted(strata.items()):
    rows.sort(key=lambda c:(hashlib.sha256(f'{SEED}:{c["family_id"]}'.encode('utf-8')).hexdigest(),c['family_id']))
    for i,c in enumerate(rows):
        c['split']='dev' if i<DEV[key] else 'test'
        allocations.append(dict(family_id=c['family_id'],stratum=key,rank=i+1,allocation_key=hashlib.sha256(f'{SEED}:{c["family_id"]}'.encode('utf-8')).hexdigest(),split=c['split']))
for split in ['dev','test']:
    rows=sorted([c for c in cases if c['split']==split],key=lambda c:c['case_id'])
    (OUT/f'{split}.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in rows),encoding='utf-8')
splitmanifest=dict(schema_version='1.0',dataset_version='debug-business-v1',seed=SEED,selection_policy='先按主要目标/决定性事实/条件建立问题族，每族一个代表；未运行任何被测 RAG。',algorithm='每个 category 分层；boundary 再按 expected_status 分层。对每族计算 SHA256(UTF8(str(seed)+":"+family_id))，按十六进制摘要、family_id 升序排列；每层前 dev_quota 个入 dev，其余入 test。与文件输入顺序无关。',dev_quota=DEV,families=families,allocations=allocations,leakage_notes=['两个 split 共享固定知识文档是预期行为。','生成 Agent 已读取 test；本次不是严格盲测。','任何题目、答案、要点、标注均不得进入知识库或伪文档。','语义近重复与跨文档必要性仍需人工核对。'])
(OUT/'split_manifest.json').write_text(json.dumps(splitmanifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
assert len(cases)==60
print(json.dumps({'cases':len(cases),'splits':dict(Counter(c['split'] for c in cases)),'categories':dict(Counter(c['category'] for c in cases)),'answered_topics':dict(Counter(c['topic'] for c in cases if c['retrieval_scored']))},ensure_ascii=False))
