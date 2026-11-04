"""Task-local authoring content. Delivered materials are DOCX/PDF, not this script."""
from pathlib import Path

ROOT = Path('D:/work/live/OBSBOT_Live')
BASE = 'business/debug/debug_impl/src/main/java/com/obsbot/live/business/debug/'
API = 'business/debug/debug_api/src/main/java/com/obsbot/live/business/debug/'
BRANCH = 'p/caijiamin/feat_debug_2th'
COMMIT = '9010928ca51c6e766f75414c49c748338e0b7ecb'
DOCS = []

def add(n, title, intro, sections, sources, tables=(), kind='docx'):
    DOCS.append(dict(n=n, title=title, intro=intro, sections=sections, sources=sources, tables=list(tables), kind=kind))

add(0,'Debug 技术资料导读与版本范围',
'本套资料面向维护 OBSBOT Live Debug 模块的开发者与测试人员，覆盖当前分支的已有代码、正在迁移的数据链路和二期建设目标。阅读时先确认能力状态，再进入对应的实现说明；设计方案不能作为已交付操作说明。',[
('资料适用范围',[
'源码基线为 OBSBOT_Live 的 '+BRANCH+' 分支，提交 '+COMMIT+'。整理日期为 2026 年 11 月 3 日。主体范围是 business/debug，App 的 withDebug 初始化、Manifest 与 Gradle 变体配置作为接入边界一并记录。',
'本套资料对源码进行静态核对，没有把 Android 编译、安装、真机运行、Start 接入或 Jenkins 构建写成已经通过的结果。文档中的检查步骤用于后续执行，验证记录需要附产物、设备和时间。']),
('阅读路径',[
'首次接手可按能力清单、SPI 入口、运行时生命周期、相机数据、性能采集、悬浮窗、导出的顺序阅读。新增数据来源时，再阅读注册接收、状态存储、字段配置和宿主适配说明。',
'表格和图解主要放在 PDF 中，包括当前架构、状态流转、导出流程、二期目标架构、迁移对照和相机字段参考。PDF 与 DOCX 是不同专题，不提供同一正文的双格式副本。']),
('状态的解释',[
'已有实现表示源码中存在具体实现路径，不等于本轮已完成运行验收。部分实现表示数据结构或局部页面已接入，但整条链路尚未闭合。设计目标表示来自二期方案，不能据此描述当前可操作能力。',
'一期方案中的完成日期是历史计划或状态记录；它们不自动证明当前提交可编译。当前代码中 API 与实现存在静态签名不一致，应先核对和修复后再执行集成验收。']),
('更新和维护',[
'代码变更后，以受影响的工作链路为单位更新正文，同时记录新的分支与提交。字段名、单位、空值规则、线程、释放时机和导出路径的变化均属于需要同步文档的变更。',
'每篇资料的源码依据列出仓库相对路径、主要符号和内容摘要校验值。它们用于回查版本；不能把本机绝对目录当作应用运行时路径。设计资料以二期方案为依据，并单列未确定的数据来源。']),
('材料的使用边界',[
'这些技术资料来自真实业务源码，不属于 demo-v1 模拟规范。示例设备名和验证场景只说明检查方法，不表示已发生现场故障、公司推广或效率提升。',
'远程处理许可需要单独管理。本套资料不携带密钥、账户实际标识或签名配置值；也不因保存到本地而自动允许上传到外部编码或生成服务。'])],['AGENTS.md',BASE+'DebugRuntime.kt',API+'IDebugService.kt'])

add(1,'Debug 当前能力与功能边界',
'当前 Debug 既保留一期的主面板、相机详情与现场导出，也出现二期通用字段模型和按设备状态存储。两套数据路径并存是理解当前能力范围的关键。',[
('已有功能入口',[
'DebugActivity 提供热区、测试网络环境、悬浮窗及字段选择等快捷设置，状态概览可点击复制。相机数据和日志导出跳转到各自 Activity；连接诊断、固件通信入口当前统一提示开发中。',
'不能根据页面上存在一个入口推断其后端能力已经实现。连接诊断时间线、固件快捷查询、通信记录和规则 Mock 在本套资料中归为二期目标。']),
('实时数据的两条路径',[
'AppPerformanceMonitor 生成 PerformanceSnapshot，一方面供旧页面读取，另一方面经 PhonePerformanceSource 转为通用设备字段，写入 Registry 与 StateStore 对应的链路。',
'CameraDebugMonitor 仍持有单份 latestSnapshot，主面板、详情和相机导出使用这一快照。DebugStateStore 支持按设备保存字段，并不能证明相机事件已经全部迁入新存储。']),
('展示配置的实际边界',[
'通用配置枚举定义主面板最多 12 个字段、悬浮窗最多 8 个字段、详情页不设数量上限。当前主要接通悬浮窗字段选择；不能把枚举的存在解释成所有页面已经完成统一配置。',
'DebugDisplayConfigStore 当前为进程内存存储。null 配置意味着使用默认值，空选择意味着用户主动不显示字段；重启后的持久化不是现有实现承诺。']),
('导出和构建边界',[
'当前导出五类选项是应用构建、账号设备、手机性能、相机数据与 App 日志。App 日志选择可读文件中最后修改的一份；快照数据取导出时可读的最新状态。',
'Gradle 已配置 withDebug 与 withoutDebug 及变体过滤。Release 的实际依赖和 APK 内容、Jenkins 产物仍需检查，配置文件不能替代产物级验证。']),
('交付状态判断',[
'现有能力清单用于说明源码范围，验收应针对具体构建、设备与固件版本执行。多设备、运行码率、相机日志、历史 CSV、折叠吸边及跨 App 使用需要分别确认实现与验证状态。'])], [BASE+'ui/main/DebugActivity.kt',BASE+'DebugRuntime.kt',BASE+'data/config/DebugDisplayConfigStore.kt',BASE+'data/export/DebugExportManager.kt','app/build.gradle'])

add(2,'Debug 入口 SPI 与初始化契约',
'Debug 对宿主提供 DebugFeature 门面，通过 RemoServiceLoader 查找 IDebugService；实现模块使用 AutoService 注册。当前分支的依赖注入改造尚有签名与类型归属问题，接入前必须核对。',[
('入口如何被装配',[
'withDebug 源集中的 DebugTailApplication 继承 TailApplication，在 onCreate 中调用 DebugFeature.initialize(this)。DebugEntryActivity 调用 DebugFeature.open 后结束自身，具体页面在 debug_impl 内。',
'DebugFeature.service 使用 loadNotNull 获取 IDebugService；因此依赖声明、SPI 生成注册和实现打包是同一条接入链路。只有 API、没有实现或注册产物时，不能假设门面会自动静默忽略调用。']),
('页面打开的 Context 规则',[
'DebugFeature.open 请求 service 创建 Intent；当 Context 不是 Activity 时加入 FLAG_ACTIVITY_NEW_TASK。DebugSDK.open 也存在类似页面打开路径，但应注意它与 SPI 门面的初始化路径并非完全相同。',
'Manifest 中 Debug 主页面、相机详情和导出页面均设置 exported=false。接入说明应记录实际 Activity 名称，包括现有 ui.cmera 包路径，不能自行改成更常见的 camera 拼写。']),
('当前静态不一致',[
'IDebugService 声明 initialize(application) 和 initialize(application, dependencies) 两个方法；DebugServiceImpl 只实现单参数版本。该实现内调用 DebugRuntime.initialize(application)，而 Runtime 定义的是要求 dependencies 的双参数版本。',
'API 侧的 IDebugService 与 DebugFeature 引用了 DebugDependencies，但该类型位于 debug_impl。debug_api 的构建依赖未声明 Impl，且架构上也不应倒依赖 Impl。这些是静态检查发现的契约问题，本轮没有执行编译来产生构建结论。']),
('后续对齐的验收要求',[
'修复时应同时确认公开依赖类型所在模块、服务方法实现完整性、门面到 Runtime 的参数传递，以及默认依赖语义。不能仅在文档里给出一个能够绕过 SPI 的调用片段，然后宣称原接入路径正常。',
'验证顺序建议先检查 debug_api 的类型可见性，再检查 debug_impl 和 KSP 注册，最后构建 App 的允许变体。文档在问题解决前保留此限制，不提供标为可直接运行的宿主 Adapter 教程。'])], [API+'IDebugService.kt',API+'DebugFeature.kt',BASE+'DebugServiceImpl.kt',BASE+'DebugSDK.kt',BASE+'DebugRuntime.kt','business/debug/debug_api/build.gradle','app/src/withDebug/java/com/remo/obsbot/live/debug/DebugTailApplication.kt','app/src/withDebug/java/com/remo/obsbot/live/debug/DebugEntryActivity.kt'])

add(3,'Debug 运行时装配与资源生命周期',
'DebugRuntime 持有采集器、相机监听、悬浮窗控制器及通用数据组件，是进程级装配中心。页面仅订阅展示所需状态，不应重复创建全局采集器。',[
('组件创建顺序',[
'初始化先创建 DebugDataRegistry、DebugStateStore、DebugDisplayConfigStore 和 DebugDataReceiverImpl，然后由 PhonePerformanceSource 注册内置设备与字段。热区控制器、性能采集器、相机监听和悬浮窗控制器分别注册生命周期或事件。',
'性能监听连接到 PhonePerformanceSource.update，Runtime 保存相同监听实例用于解除订阅。组件保存后才启动可选的宿主 dataProvider；Provider.start 接收共享 receiver。']),
('主线程和幂等性',[
'DebugSDK.initialize、open、release 检查主线程；SDK 和 Runtime 各自保存初始化标记。重复 initialize 在各自标记已设置时返回，不能用重复初始化替代变更 Provider 的正式接口。',
'startDataProvider 会比较实例、停止旧提供者再启动新实例，但目前是 Runtime 的私有初始化路径。它不等于宿主已经拥有一个公开的热切换 Provider API。']),
('页面订阅范围',[
'主页面在 onStart 加入性能、相机、热区、悬浮窗开关和字段选择监听，在 onStop 移除，并关闭弹窗。相机详情也按页面可见生命周期订阅，不负责全局事件注册。',
'新监听者是否立即收到最近值由对应组件决定：性能和相机监听会回放最新快照；Registry 的监听注册不立即回放，订阅者需要读取当前注册信息。']),
('释放顺序',[
'Runtime.release 先停止 activeDataProvider，再释放悬浮窗，移除性能转发监听并释放采集器，注销相机事件，释放热区，最后丢弃注册、状态和配置组件引用。SDK.release 还会复位自己的标记。',
'悬浮窗 release 清理 Handler、生命周期监听、弱引用和操作回调。相机 unregister 移除 EventBus 订阅、设备名请求集合和延迟回调；不要把注销理解成所有快照对象一定已经被手工置空。']),
('异常和重入检查',[
'当前初始化过程不是一个完整的失败回滚事务。若 Provider.start 或中途注册抛错，需检查是否存在部分注册资源与初始化标记不一致；这属于建议验证场景。',
'接入测试要覆盖重复初始化、重复释放、释放后重新初始化、页面切换以及 Provider.start/stop 失败。对照监听次数和事件输出，不能只以页面能打开判定没有泄漏。'])], [BASE+'DebugRuntime.kt',BASE+'DebugSDK.kt',BASE+'AppPerformanceMonitor.kt',BASE+'CameraDebugMonitor.kt',BASE+'ui/main/DebugActivity.kt'])

add(4,'Debug 主面板与测试环境操作',
'Debug 主面板是状态查看与通用调试入口。界面上的即时反馈不一定意味着底层业务配置已经重新加载，尤其需要区分测试网络开关的保存与生效。',[
('主页面入口与展示',[
'DebugActivity 使用 ActivityDebugBinding 绑定布局，onCreate 设置点击事件并读取最近性能和相机快照。概览包含应用环境、账号设备、性能及相机状态；点击概览文字可复制到剪贴板。',
'复制的是当前界面显示的文字，不会额外触发一次协议采集，也不是持续日志。主页面与相机详情、导出页面需要分别描述，避免把卡片字段当作全部协议字段。']),
('测试网络环境',[
'开关从 SPStoreManager 读取 BaseUrlManager.NET_DEBUG_MODE_KEY，无保存值时采用 BuildEnvProxy.isDebug 作为默认。切换后保存布尔值、刷新概览文字，并提示重启 App。',
'当前界面文字即时更新不能证明已经建立的网络客户端完成切换。复现环境问题时应记录开关状态、是否重启和实际请求环境；文档不应编造业务服务器地址。']),
('热区和浮窗状态同步',[
'热区开关和浮窗开关从 Runtime 读取真实状态，并订阅后续变化。浮窗关闭按钮也会改变控制器状态，主页面回到前台时需要与该状态保持一致。',
'浮窗启用时显示指标配置区域，禁用时隐藏该区域。字段配置候选来自注册中心；未注册的已选字段保留身份，不应因为暂时离线而自动删除配置。']),
('相机概览的时间含义',[
'主页面使用快照 receivedAtMillis 与当前时间比较，更新超时阈值为 2000 毫秒。这是 Debug 展示规则，并非设备连接协议中断判定，也不能直接当作网络故障结论。',
'没有快照、快照过时、某分组未有有效数据是不同情况。排查时先确认事件是否到达，再检查 Mapper 和字段显示；不要从一个占位符直接推断硬件故障。']),
('操作检查',[
'测试时分别切换主页面和浮窗上的热区操作，观察状态同步；在网络开关切换后重启，再核对真实环境。复制概览时核对内容与当前可见状态一致。',
'点击连接诊断或固件通信只得到开发中提示属于当前预期占位行为；相机详情与日志导出应进入已声明的 Activity。'])], [BASE+'ui/main/DebugActivity.kt',BASE+'DebugRuntime.kt',BASE+'ui/floating/FloatingWindowController.kt','business/debug/debug_impl/src/main/res/layout/activity_debug.xml'])

add(5,'手机性能采样机制与指标解释',
'AppPerformanceMonitor 采集当前 App 进程的性能近似状态，约每秒生成一份快照。CPU、PSS、堆内存与 FPS 使用不同测量口径，不能互相代替。',[
('采样何时启动',[
'采集器监听 Application.ActivityLifecycleCallbacks，以 startedActivityCount 记录 started 的 Activity 数。计数由零变一时启动；全部停止后取消采样与 Choreographer 帧回调。',
'采样通过主线程 Handler 以 1000 毫秒延迟循环。实际间隔可能因主线程调度变长，计算使用相邻采样的 elapsedRealtime 差值，而不是直接假设恰好一秒。']),
('CPU 使用率',[
'分子是 Process.getElapsedCpuTime 的增量，分母是经过时间再乘可用 CPU 核数，最终乘 100 并限制在 0 到 100。该值是按核心数归一化的进程 CPU 指标。',
'它不是整机总 CPU 占用，也不能与没有除核心数的监控工具直接比较。排查时同时记录设备核心数、采样时长和构建类型，避免把口径差异当作采样错误。']),
('内存口径',[
'PSS 从 ActivityManager.getProcessMemoryInfo 获取当前 PID 的 totalPss，除以 1024 显示为 MB。Java Heap 为 Runtime.totalMemory 减 freeMemory，再除以 1024 的平方；Native Heap 使用 Debug.getNativeHeapAllocatedSize。',
'这些字段不满足简单相加等于 PSS 的关系。PSS 读取失败时当前实现以零参与构造快照，这与明确的空值状态不同；解读为零内存使用之前应核实采集是否成功。']),
('帧率和温度',[
'FPS 是采样期间 Choreographer 回调次数乘 1000 再除以实际毫秒数。它表示应用帧回调频率，不是相机传感器帧率、编码器输出帧率或直播接收端帧率。',
'电池温度通过 ACTION_BATTERY_CHANGED 最近广播读取 EXTRA_TEMPERATURE，除以 10 得到摄氏度。无广播或缺失温度返回 null；不能将它称作 CPU 温度。']),
('采集和历史数据边界',[
'latestSnapshot 只保存最近一次结果，监听者注册后可立即收到它。该类没有长时间采样持久化、CSV 累积或历史区间查询。二期性能导出需要另建带时间戳的记录能力。',
'release 在主线程解除生命周期注册，停止采样、清空监听和最新值。验证应覆盖前后台、多个 Activity 重叠 started、屏幕旋转及释放后无回调。'])], [BASE+'AppPerformanceMonitor.kt',BASE+'data/source/PhonePerformanceSource.kt'])

add(6,'手机性能数据源与通用字段',
'PhonePerformanceSource 把已有性能快照接入通用设备字段体系。它负责注册和转发，不负责 CPU、内存或 FPS 的采样。',[
('固定身份',[
'内置手机设备 ID 为 sdk.phone，数据源 ID 为 sdk.phone.performance。设备类型为 PHONE，注册后绑定该来源。字段身份需要同时使用 sourceId 和 fieldId，不能只用显示名称或分组文字作主键。',
'这套注册身份用于 Debug 内部字段定位，与账号中的 DID 或相机 uniKey 不是同一个概念。文档和 Adapter 不应把固定 sdk.phone 当成真实硬件序列号。']),
('字段清单',[
'已注册字段为 cpu、memory_pss、fps、battery_temperature、java_heap、native_heap。类型均为 NUMBER；CPU 的单位为百分号，PSS 和两种堆内存为 MB，电池温度为摄氏度，FPS 按帧率解释。',
'update 传递原始数值，不提前拼接名称和单位。展示时再由通用格式器处理，避免存储中混入诸如“12 MB”的字符串，造成 NUMBER 类型检查失败。']),
('缺失与默认显示',[
'温度为 null 时 updateFields 传递 null，StateStore 移除旧温度。如此可避免新采样缺失后继续展示上一次温度，误以为它仍是实时数据。',
'未配置浮窗时默认顺序为 CPU、PSS、FPS、电池温度。Java 与 Native Heap 可在注册字段中选择，但不是默认四项。用户主动清空字段后不应再次套用默认值。']),
('接入与排查',[
'Runtime 在连接性能监听前执行 register，以保证来源和设备关系先存在。Receiver 对未绑定来源的更新会忽略，因此新增来源必须先注册设备、来源、字段并建立绑定。',
'字段有定义却没有值时，依次核对采样、PhonePerformanceSource.update、receiver 绑定和 UI 的来源解析。若值类型不匹配，浮窗可能显示占位符而不是转换后的字符串。']),
('验证方法',[
'在性能快照输入稳定值，核对六个字段写入对应 source；再把温度置空确认旧值移除。关闭再开启浮窗应保留进程内已保存选择，释放并重建 Runtime 后应重新按内存配置规则初始化。'])], [BASE+'data/source/PhonePerformanceSource.kt',BASE+'data/receiver/DebugDataReceiverImpl.kt',BASE+'data/state/DebugStateStore.kt'])

add(7,'相机状态事件采集与快照转换',
'相机状态链路以 CameraBigPushEvent 为触发，读取宿主已解析的状态并转换为 Debug 只读副本。该过程不直接解析整个固件二进制协议。',[
('事件处理',[
'CameraDebugMonitor 在 Runtime 初始化时注册 EventBus，接收线程为 MAIN。事件 uniKey 去除首尾空白后为空则直接返回；非空时用 StatusManager.queryStatus 与 RemoStatusDeviceFactory 查找状态设备。',
'查到设备后读取 cameraStatusHandle，交给 CameraDebugSnapshotMapper.map，并记录本次接收的系统毫秒时间。不存在状态设备时记录告警并返回，不会生成一个空设备的正常快照。']),
('只读转换',[
'Mapper 从 Handle 复制媒体状态、设备状态、能力和路由状态。蓝牙 MAC 的 byte 数组转为独立 List，避免后续业务修改原数组导致旧快照跟着变化。',
'设备状态以 pktVersion 不等于 -1 判断有过 Dev 数据；无有效 Dev 数据时返回 null，避免默认电量 100 被当作真实相机电量。其他分组的有效性不能直接套用同样规则。']),
('设备名称的补查',[
'设备名称取 Handle 的修改名称，不属于 0x070 大包字段。快照缺少名称时通过 DeviceCore.queryDeviceName 触发单独查询，以集合限制同一 uniKey 的重复请求。',
'名称获取失败或暂未刷新时，延迟 10000 毫秒后解除请求限制。回调会检查 monitor 是否仍注册，并核对当前快照是否仍属于相同 uniKey，防止把另一台设备名称写入当前快照。']),
('快照发布与多设备限制',[
'monitor 维护一份 latestSnapshot 并通知监听者，新监听者可以立即收到最近快照。它不是按 uniKey 保存的相机历史或多设备状态表。',
'二期已出现通用按设备状态存储，但当前相机快照没有因此自动完成迁移。多台相机交替触发事件时，需要用交替更新和名称异步回调检查数据所属设备。']),
('失败与验证',[
'事件处理异常会被捕获并记录，目标是避免 Debug 状态读取失败中断业务事件处理。旧快照可能仍然存在；UI 必须结合更新时间解释新鲜度。',
'建议覆盖空 uniKey、状态设备不存在、无 Dev 数据、设备名查询失败、切换相机、停止后异步回调和取消注册。这些是测试建议，本轮没有操作真实相机。'])], [BASE+'CameraDebugMonitor.kt',BASE+'CameraDebugSnapshotMapper.kt',BASE+'CameraDebugSnapshot.kt',BASE+'DebugRuntime.kt'])

add(8,'相机媒体模式与录像状态说明',
'媒体快照保存主子工作模式、媒体状态、开机工作模式和录像运行状态。显示层保留未确认枚举的原始数值，维护者不应依赖字段名称自行推定协议含义。',[
('主工作模式与媒体状态',[
'CameraMediaDebugSnapshot 的 mainWorkMode、subWorkMode 和 mediaStatus 分别从 Handle 对应 getter 取得。详情 Formatter 以整数显示，不在本模块中提供这些枚举的完整协议解释。',
'文档中的字段存在表示“已选入快照”，不等于设备对所有模式都支持或每个字段都有独立新鲜度。具体设备语义需要结合固件协议版本确认。']),
('开机工作模式',[
'bootUpWorkMode 包括 valid、mainWorkMode、subWorkMode 和 action。valid 用于表达开机模式数据的有效标记，不能因为数字字段为零就直接认定模式有效。',
'源码注释明确 ndiEnable、rtmpEnable 当前没有在 0x070 解析方法中写入，因此未进入该快照。不能把这些不存在字段补写成“当前 Debug 可查看”。']),
('录像状态',[
'recordStatus 保存 recording、storing、durationSeconds、deleting 和 state。前四项分别取运行状态的捕获、保存、时长和删除信息，不应合并为一个“已完成”布尔值。',
'当前记录的 state 枚举是 0 Idle、1 Starting、2 Running、3 Stopping。Formatter 对其他值输出未知并保留数值，使新固件值不会被错误归类为已停止。']),
('展示与导出的一致性',[
'详情页通过 formatGroups 读取媒体分组，复制全部和 camera_status.txt 使用 formatCopyText。新增一个快照字段后，还需检查 Mapper、Formatter 与页面消费链路，否则模型存在不代表用户能够查看。',
'通用浮窗是 sourceId 与 fieldId 模型；媒体快照的属性不会自动变成已注册浮窗字段。要在新浮窗显示它，需要明确的数据来源注册和更新路径。']),
('检查场景',[
'建议记录一次开始录像、运行、停止与保存过程，检查状态数值、布尔标记和时长是否符合真实事件顺序。未知状态时展示原值，不应让旧文档推导不存在的处理分支。',
'运行编码格式、音视频码率与分辨率属于二期新增需求，需要区分相机配置值和实际编码输出。当前媒体快照的模式和录像状态不能代替这些运行参数。'])], [BASE+'CameraDebugSnapshot.kt',BASE+'CameraDebugSnapshotMapper.kt',BASE+'ui/cmera/CameraDebugFormatter.kt'])

add(9,'相机系统电池与设备身份说明',
'dev_status 汇集系统、版本、电池与连接状态。Mapper 先判断 Dev 数据有效性，再保存选定字段；详情标题的身份尾号和完整复制文本具有不同的信息范围。',[
('Dev 数据有效性',[
'Mapper 使用 DevVersion.pktVersion 不等于 -1 作为当前 Dev 数据存在条件。判定失败时 devStatus 整体为空，详情页以不可用状态展示该分组。',
'BatteryStatus 的默认电量 100 不能独立证明有真实数据。这一有效性检查是当前实现的保护规则，仍需随协议解析变更复核。']),
('系统字段',[
'系统快照保存 powerValue、cpuTemperature、temperatureState、usbSettingMode、buzzerEnabled、ledBrightness、ledEnabled、autoSuspendTime、板级检测标记、设备型号和 SN 等字段。',
'batteryTemperatureState、batteryCapacityState、adapterPowerState 等字段取自 SystemPushStatus，与 BatteryStatus 的温度、电量字段属于不同来源。没有核实协议前不应互相换算或当作同一测量值。']),
('身份与名称',[
'deviceSn 使用 getDeviceSnNoReplace，避免把带兜底逻辑的身份误称为真实 SN；空白文本经 trim 后转 null。相机名称来自独立名称查询，不能写为大包中稳定必有的字段。',
'详情顶部身份优先取 SN，缺失时取 uniKey，再显示后四位。复制全部文本会包含完整 SN 与 uniKey；顶部只显示尾号不等于复制和导出已经全面脱敏。']),
('电池字段',[
'电池快照保存 status、capacityPercent、charging、differentialVoltage、pcbCheckFlag、voltage、temperature、powerAction、adapterPlugged、lightOperation、lightSlider。字段值按当前 getter 复制。',
'Formatter 对电量使用百分比表现，其余多个值仍为整数。电压、压差、温度的缩放和单位不应根据属性名猜测；需要协议确认后才能写成固定物理单位。']),
('蓝牙与边界',[
'蓝牙快照保留 state 和复制后的 MAC 字节列表。详情格式化将字节按十六进制连接，不能把符号字节直接当十进制地址打印。',
'系统时间、Wi-Fi、PoE、风扇、RTC 等未选中的嵌套 Bean 不在当前系统快照范围；底层 Handle 有某字段不等于 Debug 已呈现。'])], [BASE+'CameraDebugSnapshot.kt',BASE+'CameraDebugSnapshotMapper.kt',BASE+'ui/cmera/CameraDebugFormatter.kt'])

add(10,'相机版本连接标记与能力说明',
'版本、连接和能力字段辅助理解设备状态，但不能替代连接过程诊断。当前详情对版本保留十进制和十六进制原值，对连接标记显示布尔结果。',[
('版本字段',[
'版本快照包括 packetVersion、fallbackVersion、产品与平台类型，以及相机、镜头、TOF、电池、AI、云台、蓝牙、系统管理、遥控器、子 MCU、转轴等组件的版本。',
'Mapper 将版本 0 和 -1 转为 null；空字符串类型信息也转为 null。详情 formatVersionRaw 显示整数及十六进制，不应把这些原值直接当作已经拆好的四段固件版本字符串。']),
('连接标记',[
'连接快照保留 AI、云台、电池、镜头、TOF、蓝牙在线，以及 USB Wi-Fi、PoE、转轴底座、UWB、音频接口、HDMI、PX30、SD 卡、遥控器等连接标记。',
'sensorError 与 mediaError 是异常布尔标记，不应按“是否连接”同向解释。voiceDeviceAttached 是三个音频接入标记的逻辑或，属于计算字段，不是额外接收的协议字段。']),
('连接诊断的区别',[
'这些标记描述某次快照下的组件状态，不记录发现、网络准备、建链、认证、重试等阶段耗时。看到状态标记不能声称当前已有全链路连接时间线。',
'断开原因、重连次数、通道耗时等目标数据应由宿主连接事件接入。它们需要事件身份、时间戳和设备关联，不能由静态布尔状态可靠反推。']),
('能力与路由',[
'capability 当前只有 supportBroadcasting 和 supportUsbMic，直接从 CameraStatusHandle 获取。能力表示设备支持某功能，不表示本次会话正在使用该功能。',
'routerStatus 有 totalCount、appCount、monitorCount、pcCount。它们是路由统计原值，不是网络时延、丢包率或完整连接历史；总数与分项的业务关系仍需协议确认。']),
('维护规则',[
'新增协议版本时先确认 getter 和无效值约定，再更新快照和 Formatter。对新枚举尽量保留原值，在未确认语义前避免编造中文状态。',
'完整相机字段的显示 ID、标签、值来源和格式化调用见字段参考 PDF，可结合本篇理解版本与连接的边界。'])], [BASE+'CameraDebugSnapshot.kt',BASE+'CameraDebugSnapshotMapper.kt',BASE+'ui/cmera/CameraDebugFormatter.kt'])

add(11,'相机详情页面与文本复制',
'相机详情页消费 CameraDebugSnapshot，以四个固定分组组织字段，Formatter 负责解释显示文本，Adapter 负责列表和展开状态。页面本身不拥有协议监听。',[
('页面数据生命周期',[
'onCreate 设置布局，onStart 注册相机快照监听，onStop 移除监听。全局 CameraDebugMonitor 继续保存最近快照，页面停止不等于相机事件停止。',
'未收到快照时显示空状态；收到后更新名称、型号、身份尾号、更新时间和分组。页面持有自己的 latestSnapshot 用于复制，注意与 monitor 的同名字段区分。']),
('分组与稳定身份',[
'四个固定分组 ID 为 media_status、dev_status、capability、router_status。字段拥有稳定 id、label、value，DiffUtil 用身份和内容决定列表更新。',
'媒体与设备状态首次默认展开，能力与路由默认不展开。后续快照刷新保留用户的分组展开状态，不应该每次全部展开导致列表跳动。']),
('格式化职责',[
'CameraDebugFormatter 负责布尔、整数、时长、百分比、版本和 MAC 等显示。不可用值用双短横线表达；未知录像状态保留数值。Adapter 不应自行二次解释固件枚举。',
'章节中的“支持某能力”和“正在某状态”需要分开。Formatter 只产生显示数据，不重新读取固件，也不会保证几组字段来自同一底层协议更新时间。']),
('复制全部',[
'formatCopyText 生成名称、型号、设备 SN、uniKey、最后更新时间，然后追加全部四组字段。复制功能没有快照时提示暂无可复制状态。',
'复制全部与顶部尾号显示不同，文本可能包含完整设备标识。向问题单或外部渠道转发前应按实际资料许可处理，不能把界面尾号截断推断成整个文本已脱敏。']),
('页面验证',[
'检查空状态、首次收到数据、连续刷新、手动折叠后继续更新、离开再进入、复制全部和未知值显示。两台相机交替更新时确认当前页面所读仍是单快照语义。',
'现有包名 ui.cmera 是源码事实。修改路径时需要同步 Manifest 和导入关系；本文不建议为文档整齐而直接更改生产代码命名。'])], [BASE+'ui/cmera/CameraDebugDetailActivity.kt',BASE+'ui/cmera/CameraDebugDetailAdapter.kt',BASE+'ui/cmera/CameraDebugFormatter.kt','business/debug/debug_impl/src/main/AndroidManifest.xml'])

add(12,'设备数据源字段注册与接收契约',
'通用数据模型把设备、来源、字段定义与实时值分开。Receiver 是宿主与内置来源提交数据的入口，Registry 描述“有什么”，StateStore 描述“最新值是什么”。',[
('注册顺序与身份',[
'设备使用 DebugDevice(id,name,type)，来源使用 DebugDataSource(id,name)，字段用 DebugFieldDefinition 描述 id、名称、分组、类型、单位。先注册设备与来源，再注册字段并 bindSource。',
'registerFields 要求来源已经存在；bindSource 要求设备和来源都存在。相同 ID 会更新对应条目，字段 ID 在所属来源内唯一；跨来源重名需要 DebugFieldKey 区分。']),
('更新接收',[
'DebugDataReceiverImpl.updateFields 检查设备是否绑定该来源。没有绑定则返回，不会隐式创建设备；已绑定则将 map 转交 StateStore。',
'Receiver 当前没有完整检查每个 fieldId 是否已注册、每个值是否符合字段类型。来源应主动遵守字段定义，不能认为下游已经完成所有 schema 校验。']),
('解除和清理',[
'unregisterDevice 先清设备实时值再注销设备。unbindSource 只清指定设备对应来源的值，再解除绑定。unregisterSource 清所有设备该来源的值并删除来源字段及绑定。',
'注销某设备不等于全局删除来源，因为相同来源可能仍服务其他设备。操作顺序会产生状态和注册变化通知，UI 应按当前快照读取，不能缓存失效的对象引用。']),
('注册变化通知',[
'Registry 在锁内执行更新并复制监听集合，锁外逐个回调。监听回调在发起更新的线程执行，不保证主线程；字段注册变化与实时值变化是两类通知。',
'浮窗将两类变化合并投递到主线程，注册变化还需要重建候选项。新接入页面若直接在注册回调操作 View，会引入线程问题。']),
('宿主接入检查',[
'最小验证序列是注册设备、来源、字段、绑定、更新、读取、置空、解绑和注销。每一步核对注册列表、实时值和 UI 表现，不以存在接口作为完整接入证明。',
'Provider.start 与 stop 负责宿主事件订阅和释放。当前公开类型归属仍需对齐；这里描述的是现存契约语义，而非宣布跨 App 集成已经完成。'])], [BASE+'domain/provider/DebugDataProvider.kt',BASE+'domain/provider/DebugDataReceiver.kt',BASE+'data/registry/DebugDataRegistry.kt',BASE+'data/receiver/DebugDataReceiverImpl.kt',BASE+'domain/model/DebugFieldDefinition.kt'])

add(13,'实时状态缓存与并发通知',
'DebugStateStore 以设备、来源和字段三层键保存最新值，负责进程内实时缓存。它不负责来源定义、设备发现、历史记录和持久化。',[
('存储结构与更新',[
'内部结构为 deviceId 到 sourceId 再到 fieldId 的可变 map。updateFields 对传入字段批量覆盖，null 表示删除该字段；未传入的其他字段保留原值。',
'空更新 map 直接返回。字段删除后，空的来源 map 与设备 map 会被清理，防止空容器持续堆积。全量替换来源数据时，不能只省略字段并期待旧值自动消失。']),
('读取与对象边界',[
'getFieldValue 返回单字段值；getFields 返回该来源 map 的副本。副本保护容器本身，不代表 Any 类型的嵌套对象已经深拷贝；来源宜提交不可变或独立复制的数据。',
'字段定义和实时值属于不同组件。读取前可以结合 Registry 验证来源绑定，不要仅凭 StateStore 中曾存在一个值就认定设备仍然在线。']),
('同步与通知',[
'更新和读取通过 synchronized 保护内部结构，写入后通知监听。监听者需要考虑回调线程与更新线程一致，且多次更新可能导致多次通知。',
'将 UI 刷新放到主线程并做合并，可以避免高频数据更新直接重绘。当前浮窗用 refreshPending 与 registryRefreshPending 合并任务，属于消费端的行为。']),
('清理语义',[
'clearDevice 删除设备所有来源值；clearDeviceSource 删除一台设备一个来源；clearSource 删除所有设备的同一来源；clear 删除全部实时缓存。',
'Receiver 调用清理时还会维护 Registry，单独调用 StateStore 不会自动删除设备定义。业务应通过正确所有者执行组合操作。']),
('新鲜度与历史能力',[
'StateStore 的值没有通用时间戳、TTL 或 stale 状态，因此“有值”不等于“刚更新”。相机旧链路的 receivedAtMillis 不能自动提供给所有通用字段。',
'长时间性能导出需要另行采样存储、保留策略和查询接口。将内存最新值 map 导出成 CSV 不能称为时间序列历史导出。'])], [BASE+'data/state/DebugStateStore.kt',BASE+'data/receiver/DebugDataReceiverImpl.kt',BASE+'ui/floating/FloatingWindowController.kt'])

add(14,'展示字段配置与选择交互',
'展示配置保存页面选择了哪些字段，不保存字段定义或实时值。当前内存配置与浮窗两级选择器已经连接，主面板和详情的统一字段配置仍需分别确认。',[
('配置对象与限制',[
'DebugDisplayTarget 定义 MAIN_PANEL 最多 12 项、FLOATING_WINDOW 最多 8 项、DETAIL_PAGE 不限制数量。DebugDisplayConfig.isValid 同时检查去重后的数量与最大项数。',
'字段使用 sourceId 与 fieldId 的组合身份。两个来源中显示名称相同的 CPU 字段仍是不同选项，不能按中文名称去重。']),
('没有配置与空配置',[
'ConfigStore.getConfig 返回 null 表示尚未保存选择，需要使用默认字段；已保存空列表表示用户主动取消全部。浮窗在空列表时显示没有指标的提示，不能强行回填默认四项。',
'读取和保存都复制 selectedFields 列表，避免调用方修改列表结构影响内部配置。当前 ConfigStore 仅为内存 map，进程退出后不承诺恢复，注释中的后续 SharedPreferences 不是已实现能力。']),
('两级列表',[
'FloatingMetricConfigAdapter 从字段定义生成分组选项，一级标题可展开，二级显示字段。一级复选框根据子项数量显示未选、全选或半选；初次打开时分组默认收起。',
'选择结果保留顺序，组内操作应遵守最大项数，超过限制反馈提示。选择器的分组收起与浮窗本体折叠是两种交互，不能混称为已经实现浮窗折叠。']),
('注册变动与失效项',[
'已选字段暂未注册时保留其组合标识，出现在未注册分组中，仍占选择名额。来源重新注册后可恢复匹配，避免临时离线就丢失用户偏好。',
'Registry 变化时控制器更新选择器候选并通知主页面摘要。实时值变化只需重绘内容，不应每次重建用户选择顺序。']),
('检查方法',[
'测试未配置、主动空选、重复项、超限、跨来源同名字段、删除来源和重新注册。分别检查摘要、选择器和浮窗实际行顺序。',
'如果后续加入持久化，应定义 ID 变化迁移、版本兼容和损坏配置回退；现有内存行为不能作为跨重启偏好保存的验收结果。'])], [BASE+'domain/config/DebugDisplayConfig.kt',BASE+'data/config/DebugDisplayConfigStore.kt',BASE+'ui/floating/FloatingMetricConfigAdapter.kt',BASE+'ui/floating/FloatingWindowController.kt'])

add(15,'应用内悬浮窗行为与生命周期',
'当前性能悬浮窗是挂在 Activity 内容区域内的普通 View。它随宿主页面生命周期移动，不是系统级跨应用悬浮窗。',[
('挂载与页面切换',[
'控制器在 onActivityResumed 保存 Activity 弱引用，启用时将 FloatingPerformanceView 加到 android.R.id.content。相同父容器已有 View 时复用并刷新；切页时移除旧 View 并新建。',
'onActivityPaused 在当前 Activity 对应时关闭配置弹窗并移除浮窗。回到前台根据 isEnabled 再挂载；浮窗移除不自动关闭全局启用状态。']),
('位置和拖动',[
'拖动手势绑定在指标文字区，底部面板、热区、配置、关闭按钮保持点击行为。MOVE 依据 raw 坐标增量更新位置，并限制在父容器宽高内。',
'UP 和 CANCEL 保存位置，控制器用 lastX、lastY 在新页面恢复并校正范围。当前是内存位置记录；没有浮窗本体折叠状态机和靠边阈值吸附实现。']),
('数据选择',[
'控制器从 Registry 读取字段定义，从 StateStore 读取实时值。手机来源须唯一匹配绑定设备；相机来源还要求设备 ID 与 currentCameraDeviceId 一致。',
'无法唯一确定设备时不读取值，避免随机取第一台相机。currentCameraDeviceId 有设置方法，但不能仅凭该方法存在宣称所有相机选择页面已接入。']),
('刷新与显示',[
'后台来源通知经 Handler 切到主线程，同一时刻多个更新合并为一个待执行任务。注册信息变化还同步候选字段；释放后不再处理刷新。',
'TEXT 需要 String，NUMBER 需要 Number，BOOLEAN 需要 Boolean；类型不匹配或无值显示占位符。ENUM 当前使用值的字符串形式，不代表已有所有业务枚举的中文翻译。']),
('快捷操作与边界',[
'面板按钮打开 DebugActivity，已经在该页则不重复打开；热区按钮切换全局热区状态；配置按钮打开 ListPopupWindow；关闭按钮通过 setEnabled(false) 同步主页面状态。',
'二期拟增加折叠展开和近边吸附，页面旋转仍需专项测试。当前拖动限制和恢复位置的 clamp 不能替代完整旋转、分屏和窗口 Insets 验收。'])], [BASE+'ui/floating/FloatingWindowController.kt',BASE+'ui/floating/FloatingPerformanceView.kt',BASE+'DebugRuntime.kt'])

add(16,'可操作控件热区检测',
'热区功能通过包装 Activity 内容布局，在原页面绘制完成后标记可操作 View 的矩形区域。它帮助检查控件范围，不测量实际点击成功率或触摸事件命中结果。',[
('控制器与页面包装',[
'HighlightOverlayController 注册 Application 生命周期回调，在页面 resumed 时获取内容区域第一个子 View。如果已经是 HighlightFrameLayout 则复用，否则移除原根 View，装入新的包装容器，再放回原位置。',
'控制器使用弱引用集合跟踪包装层，避免单纯因为集合持有导致页面不能回收。包装是对 View 树的修改，测试时需检查布局参数、层级和与浮窗挂载顺序的关系。']),
('绘制规则',[
'dispatchDraw 先绘制正常子内容，开关打开时递归访问可见 View。isClickable、isLongClickable、isScrollContainer 任意满足即视为可操作，包装层自身除外。',
'通过 getDrawingRect 和 offsetDescendantRectToMyCoords 转换坐标，再绘制半透明红色填充与红色边框。它是矩形几何区域，不能完全表达复杂裁剪、遮挡和自定义触摸命中。']),
('状态与滚动',[
'全局开关保存在 HighlightFrameLayout.isHighlightEnabled，控制器同步所有包装层请求下一帧重绘。主页面与浮窗热区按钮调用同一状态入口。',
'包装层在 attached 时注册滚动观察者，detached 时解除。滚动发生且热区开启时重新绘制，以跟随可操作控件的位置变化。']),
('释放与限制',[
'release 在主线程关闭热区、解除生命周期注册、清空监听与集合。已经包装的 View 树不在这里逐一拆回原结构，热区关闭表示停止覆盖绘制，不能写成完全恢复原层级。',
'此递归基于 Android View 树。没有证据时不应宣称能识别 WebView 内部 DOM、独立 Surface 内容或全部 Compose 语义节点。']),
('验证建议',[
'覆盖点击、长按、滚动容器、不可见控件、列表滚动、页面切换和重复 resumed。检查同页不会多层包装，并观察开启后按钮行为是否保持。',
'热区有颜色只说明满足当前判定条件；若用户点击无响应，仍需检查遮挡、触摸分发、禁用状态和业务点击监听，不能只凭红框定位原因。'])], [BASE+'ui/highlight/HighlightOverlayController.kt',BASE+'ui/highlight/HighlightFrameLayout.kt',BASE+'ui/main/DebugActivity.kt'])

add(17,'现场数据收集与 ZIP 组织',
'DebugExportManager 根据页面选择收集现场信息，写入一个 ZIP。当前主要导出最新快照和一份 App 日志，不提供历史时间区间查询。',[
('导出选项与校验',[
'DebugExportOptions 有 includeAppBuild、includeAccountDevice、includePerformance、includeAppLog、includeCameraData 五项。hasSelection 只要任意一项为真即有效，全空选择会在页面和管理器分别阻止。',
'App 日志被选中但没有找到可读日志时抛错，不能把没有日志的导出伪装成已成功收集日志。相机数据通过 Runtime.latestCameraSnapshot 读取，再用 Formatter 转为文本。']),
('日志文件的选择',[
'日志目录来自 DirectoryPath.getLogPath。管理器扫描可读普通文件，以 lastModified 最大值选中一份。文件修改时间是挑选文件的依据，不等于日志中每条记录都在某个用户指定区间内。',
'当前没有 startTime/endTime 选项，也没有按日志行时间过滤或合并多文件的逻辑。跨天现场、轮转日志和时间范围导出属于二期需要补充的能力。']),
('文件组织',[
'应用、账号设备和性能信息按选择组织到 debug_summary.txt；相机状态放入 camera_status.txt；原日志放在 app_log 子目录。具体状态取生成时可读的最近快照。',
'导出目录为 DirectoryPath.getDefaultOutFolder 下的 DebugExport。ZIP 名称包含手机型号、DID 后四位和 yyyyMMdd_HHmmss 时间片段，并经过文件名字符处理。']),
('异常与历史保留',[
'写 ZIP 时异常会尝试删除尚未完成的文件并重新抛出。成功创建后，按最后修改时间保留最近五个 ZIP，清理更旧的 ZIP。删除返回值没有形成完整的清理结果报告。',
'“成功或取消后立即删除临时副本”是旧模拟资料中的规则，不能移植为真实项目现状。这里的导出产物按最近五份保留，系统分享取消也未实现专门的立即删除回调。']),
('真实性与范围',[
'现场性能是一份快照，不是持续性能历史。相机状态文本不是相机内部日志；App 日志也不等于固件日志。这三类来源在二期扩展时应分别命名和验收。',
'名称中只保留 DID 尾号不能证明 ZIP 内容全面脱敏。复制和导出的完整身份字段需要结合实际数据使用范围审查，本套文档不使用真实标识值作示例。'])], [BASE+'data/export/DebugExportManager.kt',BASE+'ui/export/DebugLogExportActivity.kt',BASE+'ui/cmera/CameraDebugFormatter.kt'])

add(18,'导出页面系统分享与失败处理',
'导出页面负责选项交互、后台任务、状态提示和系统分享。ZIP 生成成功与接收 App 成功保存是不同阶段，页面当前主要确认前一阶段。',[
('选项交互',[
'全选框控制五个子选项，子选项变化后反算是否全选，isUpdatingSelection 防止监听互相递归触发。点击生成按钮时读取一次当前选择，再将该快照传给任务。',
'任务进行中禁用按钮、全选及各选项，并显示进度。未选任何内容只显示提示，不进入文件创建逻辑。']),
('协程和生命周期',[
'任务在 lifecycleScope.launch 中执行，ZIP 创建通过 withContext(Dispatchers.IO) 放到 IO 调度器。返回主线程后更新状态并打开分享面板，finally 恢复控件状态。',
'当前 catch 捕获 Throwable，也包括需要谨慎处理的取消场景。页面销毁、返回和旋转过程中 ZIP 是否继续、如何清理残留，需要实际生命周期验证，不能称为已具备持久化后台导出任务。']),
('FileProvider 分享',[
'页面通过 FileProvider.getUriForFile 获取 content URI，authority 使用当前 packageName 加 .debug.fileprovider。Manifest 使用 applicationId 对应占位符，必须与运行变体保持一致。',
'分享 Intent 使用 ACTION_SEND、application/zip、EXTRA_STREAM、ClipData，并加 FLAG_GRANT_READ_URI_PERMISSION。接收方只获得对应 URI 的临时读取权限，不是应用目录的任意读取能力。']),
('可分享目录',[
'debug_file_paths.xml 分别声明 external-files-path 与 files-path，两者相对路径均为 OBSBOT/DebugExport。导出真实目录必须落在对应根下，否则 URI 创建会失败。',
'外部应用专属目录不可用时底层工具是否回退到内部目录，需要结合 DirectoryPath 实现确认。本 XML 同时提供两个可分享范围，不等于本轮实际验证过所有存储模式。']),
('结果判定',[
'页面在 ZIP 创建完成后先写成功状态再启动 chooser。没有接收方确认协议，因此不能根据这个成功提示声称用户已在目标应用保存文件，或取消分享已完成清理。',
'建议检查空选项、无日志、无相机快照、目录被同名文件占用、创建失败、分享无可用应用、取消分享及存储紧张。验收要检查 ZIP 实际条目和内容，而非只看 Toast。'])], [BASE+'ui/export/DebugLogExportActivity.kt',BASE+'data/export/DebugExportManager.kt','business/debug/debug_impl/src/main/AndroidManifest.xml','business/debug/debug_impl/src/main/res/xml/debug_file_paths.xml'])

add(19,'宿主能力适配与跨 App 接入边界',
'二期方向是通用 Debug SDK 加宿主 Adapter。当前已定义数据提供和接收契约，但相机旧链路、API 类型归属与默认初始化尚未全部完成迁移。',[
('谁负责什么',[
'宿主 Provider 负责监听产品事件、选择真实设备身份、转换业务状态并提交 receiver；SDK 负责通用字段注册、最新值缓存、展示和通用性能采集。',
'宿主未提供的能力应隐藏或禁用属于目标行为。当前 DebugDependencies 只含可选 dataProvider，不能把规划图中的日志、通信、缓存清理等所有能力都写成已存在的依赖接口。']),
('当前接入情况',[
'DebugTailApplication 目前调用无依赖参数的 DebugFeature.initialize。扫描 App 与业务接入范围未见一个明确实现 DebugDataProvider 的 Live Adapter；这不代表其他仓库或未来分支不存在实现。',
'CameraDebugMonitor 仍直接使用 StatusManager、RemoStatusDeviceFactory 和 DeviceCore。debug_impl 的 Gradle 依赖也保留 common:command 与 device_core_api，因此独立宿主边界尚未完全形成。']),
('接口归属与公开边界',[
'DebugDataProvider、Receiver 及通用模型目前位于 debug_impl；API 方法又引用 Impl 中的 DebugDependencies。公开契约需要对齐所在模块，不能引入 API 到 Impl 的反向依赖补洞。',
'目标设计还要遵守仓库 business API/Impl 与分层规则。文档中的 UI、Domain、Data 表示模块内部职责，不能直接推断已经拆成三个独立发布 AAR。']),
('接入步骤的前置条件',[
'先解决初始化签名与类型可见性，再选择一个最小只读设备来源接入。Adapter 在 start 注册与绑定，更新时传值，在 stop 解除宿主订阅；设备删除应清理对应状态。',
'Start 接入需要在 Start 仓库检查真实依赖、应用生命周期、设备模型和 UI 资源。当前只核对 Live 仓库，不宣称已实现 Start 接入和产品兼容。']),
('跨 App 验收',[
'分别记录宿主支持能力、未支持能力的 UI 行为、设备 ID 规则、字段单位和线程。检查没有业务模块直接导入另一业务 Impl，也没有为 SDK 复制业务通信代码。',
'复用成功应有独立构建、安装与设备验证记录。复用计划、接口定义和架构图都不能代替这些证据。'])], [BASE+'DebugDependencies.kt',BASE+'domain/provider/DebugDataProvider.kt',BASE+'domain/provider/DebugDataReceiver.kt',BASE+'CameraDebugMonitor.kt','business/debug/debug_impl/build.gradle','app/src/withDebug/java/com/remo/obsbot/live/debug/DebugTailApplication.kt','AGENTS.md'])

add(20,'Debug 扩展维护与问题定位',
'新增能力应沿数据来源、模型、存储、展示和导出逐层确认；故障定位也按相同方向进行。局部新增一个属性或控件不足以形成完整可用功能。',[
('增加手机或通用字段',[
'确认数据所有者和采样含义，再注册稳定 sourceId、fieldId、类型、单位与分组。先绑定设备来源，之后推送原始值；缺失值使用 null 移除，避免格式化文本污染 NUMBER 类型。',
'检查选择器候选、最大项数、默认字段、失效项保留和读取设备身份。新来源回调可以在后台，UI 必须调度到主线程。']),
('增加相机快照字段',[
'在固件或宿主状态 getter 中确认语义及有效性，在 Snapshot 添加只读值，并由 Mapper 明确复制。随后更新 Formatter 的稳定字段 ID、标签和显示规则。',
'核对主面板、详情、复制与相机导出是否需要展示该字段。若要进入通用浮窗，另需注册来源和转发链路，不能依赖旧快照属性自动出现。']),
('没有数据显示',[
'先区分无设备、无事件、无有效分组、无注册、无绑定、无实时值、设备选择不唯一和格式类型错误。按证据排查，不先假设硬件坏了。',
'相机检查 uniKey、状态查询、Mapper 的 Dev 判定、最近快照时间及页面监听。通用字段检查 Registry 与 StateStore；浮窗还要检查启用、当前 Activity 和当前相机 ID。']),
('配置或位置异常',[
'配置重启后恢复默认符合当前内存实现；若用户清空后立即回默认，检查 null 与空列表是否被混同。失效字段占用名额是当前保留策略，不应未经确认自动删除。',
'浮窗切页消失需核对 resumed/paused、启用状态及父容器，无法拖动需确认触摸发生在指标文字区。配置分组的折叠不是浮窗本体折叠。']),
('编译与发布排查',[
'当前优先检查 IDebugService 未完整实现、DebugDependencies 位于 Impl 和 Runtime 初始化参数不一致。源码证据足以形成待修项，但最终修复需要构建结果。',
'路径迁移必须同步 namespace、Manifest、SPI、资源、Gradle 与调用方。不要通过扩大 api 传递、反射或增加违规依赖隐藏契约问题。'])], [BASE+'DebugRuntime.kt',BASE+'data/receiver/DebugDataReceiverImpl.kt',BASE+'ui/floating/FloatingWindowController.kt',API+'IDebugService.kt','AGENTS.md'])

add(21,'Flavor 编译隔离与构建核验',
'App 通过 debugCapability 维度决定 Debug 实现是否参与编译。源码中存在过滤规则与专属源集，产物中是否完全排除实现仍需独立核验。',[
('变体选择',[
'productFlavors 定义 withDebug、withoutDebug。beforeVariants 关闭 withDebugRelease，同时关闭 withoutDebugDebug 和 withoutDebugStaging；目标保留 withDebugDebug、withDebugStaging、withoutDebugRelease。',
'App 以 withDebugImplementation 同时依赖 debug_api 和 debug_impl。withDebug 源集包含专用 Application、入口 Activity 和 Manifest，不靠运行时 if 隐藏所有实现。']),
('入口与资源参与打包',[
'withDebug Manifest 替换 Application 为 DebugTailApplication，并声明非导出的 DebugEntryActivity。debug_impl Manifest 合并主面板、相机详情、导出与 FileProvider。',
'Release 核验不能只搜索 Java 类。还应检查 Manifest 组件、资源、SPI 注册、依赖图和入口字符串，确认没有其他依赖路径把 Impl 带入产物。']),
('架构依赖规则',[
'仓库采用 app 到 business、common、core-common、infra 的依赖方向，业务 Impl 只能依赖业务 API。gradle/module-dependency-rules.gradle 是执行约束的事实来源。',
'当前 debug_impl 依赖自身 API、通用模块与 device_core_api；这符合部分仓库允许关系，但不等于目标 SDK 已完全脱离 Live 业务。两种“解耦”判断应分开。']),
('建议执行的核验',[
'先执行 checkModuleDependencies，再检查 Gradle 实际任务名并构建允许的 App 变体。对 withDebugDebug 和 withDebugStaging 检查入口可用，对 withoutDebugRelease 检查 Debug 实现与组件不存在。',
'Jenkins 需保存分支、提交、变体、任务、产物和检查结果。本套资料只核对配置，不把二期表中的“已完成”直接作为本轮 Jenkins 通过证据。']),
('构建阻断与敏感配置',[
'接口类型和初始化签名的不一致需要在构建前处理，否则隔离测试可能尚未到达产物阶段就失败。失败原因应与是否隔离正确分开记录。',
'构建资料不复制签名密码、私有仓库凭据或环境密钥。接入者通过既有安全配置获得环境，不应在知识文档里粘贴整段含凭据的 Gradle 文件。'])], ['app/build.gradle','app/src/withDebug/AndroidManifest.xml','business/debug/debug_impl/src/main/AndroidManifest.xml','business/debug/debug_impl/build.gradle','gradle/module-dependency-rules.gradle',API+'IDebugService.kt'])

add(22,'Debug 验证计划与验收记录要求',
'本篇给出当前能力和二期目标的检查方法。用例是后续执行计划，不是已通过报告；每项结果应关联具体构建、设备、固件和证据。',[
('执行前记录',[
'记录仓库提交、构建变体、应用版本、Android 版本、设备型号与固件版本。涉及多设备时分别记录脱敏设备标识及连接方式，区分应用日志和固件日志来源。',
'当前静态契约问题应先修复并完成编译。测试环境、签名或私有依赖缺失时记录阻断，不能写成用例失败或业务不支持。']),
('基础功能',[
'主面板核对入口、概览复制、测试环境重启提示、热区与浮窗双向同步。性能核对前后台停启、采样间隔和指标口径，不能拿摄像头帧率验证 App FPS。',
'相机核对无事件、首包、无 Dev 数据、名称补查、四组详情、折叠状态保留和复制内容。导出核对五种选项及组合、无日志、无相机快照、ZIP 条目和最近五份清理。']),
('通用字段与多设备',[
'两台设备使用相同 fieldId 但不同设备身份，交替写入不同值；切换选择、解绑和注销时检查没有串值。跨来源同名字段要保持独立，空值应删除旧数据。',
'分别验证 Registry 回调、StateStore 更新与 UI 主线程调度。对于未接通的相机 Adapter，不把直接向内存写值的测试当作真实相机链路通过。']),
('二期能力',[
'时间区间导出要覆盖边界、时区、跨文件与部分来源失败。性能 CSV 要核对时间戳、缺失值、采样频率和历史保留；相机日志需要确认固件接口和失败反馈。',
'折叠吸边要覆盖阈值内外拖动、页面切换、旋转和关闭。连接诊断与通信 Mock 需要独立规则、超时、取消和设备隔离测试，未实现时记录为待实施。']),
('架构与效率',[
'构建验收保存依赖检查、允许变体、Release APK 内容和 Jenkins 证据；跨 App 验收需要 Live 与 Start 分别执行。不能用 Live 的结果替代 Start。',
'效率评估先选固定任务，如获取现场信息、定位某字段和新增宿主来源，记录原流程与新流程时间、失败次数及样本数。结果由测量填写，不预设节省比例。'])], [BASE+'ui/main/DebugActivity.kt',BASE+'AppPerformanceMonitor.kt',BASE+'data/export/DebugExportManager.kt','app/build.gradle','AGENTS.md'])

add(23,'Debug 二期建设目标与实施约束',
'二期目标是在一期集中管理调试能力的基础上，增强多设备、音视频运行信息、现场导出与高级诊断，并逐步形成通用 SDK 与宿主 Adapter。以下为设计目标及待确认事项。',[
('多设备与运行参数',[
'目标按设备唯一标识保存最新状态，并由宿主 Adapter 转为统一模型。各页面按当前设备读取，避免单份 latestSnapshot 被另一台设备覆盖；设备发现、断开和重连需要明确清理策略。',
'编码格式、分辨率、音视频码率要分别注明来源是相机配置、编码器运行值还是传输统计。尚未确定的来源保留待确认，不能拿配置参数填作实时测量。']),
('导出与交互',[
'目标 App 日志按时间范围提取，快照类数据取导出时状态，相机日志通过待确认的固件接口获取，长时间性能记录带时间戳保存并导出 CSV。统一导出流程应明确部分失败规则。',
'浮窗增加关闭、展开、折叠状态，拖至边缘附近可吸附，正常位置保留自由拖动。需处理页面切换和方向变化的可显示区域，不强制每次松手吸边。']),
('测试状态与高级能力',[
'缓存清理和测试状态重置先展示影响范围并确认。SDK 处理自身配置和通用缓存，宿主处理业务数据；授权状态重置不能假定由 SDK 直接删除宿主所有数据。',
'连接诊断观察宿主已有事件并形成阶段时间线，不改变连接重试策略。固件调试复用现有通信，Mock 按规则返回模拟响应并进入既有解析链路；未命中规则继续真实通信是设计行为。']),
('架构与跨 App',[
'目标内部按 UI、Domain、Data 分工，宿主特有的事件监听、账号环境和协议转换移到 Adapter。Dependencies 负责装配，能力注册决定页面是否可用。',
'当前类型归属和 SPI 初始化问题需要先解决；仓库目录分层也需遵守。跨 App 计划先完成 Live 迁移，再在 Start 验证，不把接口草案或一张架构图当作复用完成。']),
('工期与依赖',[
'用户提供的二期表对功能增强、架构升级、适配和跨 App 分别给出工作日估算。它们是方案中的估计，实际排期依赖固件接口、设备可用性、构建环境和边界确认。',
'验收分别覆盖功能、架构与编译隔离、跨 App 和效率评估。每次交付更新能力矩阵与证据，保留未完成项，避免后续资料把目标误读为现状。'])], [BASE+'DebugDependencies.kt',BASE+'CameraDebugMonitor.kt',BASE+'data/state/DebugStateStore.kt','app/build.gradle'])

add(24,'Debug 当前架构与调用关系图解',
'本图解描述当前代码的主要调用关系。图中的传统快照链路和通用字段链路并行存在，公开初始化契约仍有待对齐项。',[
('当前装配与生命周期',[
'App 的 withDebug 入口经过 DebugFeature 和 IDebugService 到 DebugServiceImpl。当前实现调用与 Runtime 签名存在不一致；图上的连接表达意图和现有符号关系，不代表该提交已构建通过。',
'Runtime 创建采集器和注册存储，页面订阅展示状态；生命周期结束时按所有权释放。相机事件仍由 CameraDebugMonitor 直接监听宿主协议相关事件。']),
('两条数据路径',[
'旧路径以 CameraDebugSnapshot 和 PerformanceSnapshot 为中心，供主面板、相机详情、现场导出读取。新路径由 PhonePerformanceSource 把性能数据转成注册字段并更新 StateStore，浮窗从通用存储读取。',
'新存储支持多个设备不等于旧相机链路已迁入。迁移时需要明确字段映射和设备选择，不应在同一界面混用不同设备的缓存。'])], [BASE+'DebugRuntime.kt',BASE+'DebugServiceImpl.kt',BASE+'CameraDebugMonitor.kt',BASE+'ui/floating/FloatingWindowController.kt'],kind='pdf')

add(25,'设备字段更新与悬浮窗刷新图解',
'图解覆盖注册、绑定、更新、通知、设备解析和字段展示。无绑定更新被忽略，空值删除旧值，主线程任务合并用于控制刷新频率。',[
('设备来源绑定',[
'来源先注册，再注册字段；设备与来源都存在才能绑定。Receiver 接收更新后检查绑定，未绑定直接返回。相同来源可服务多个设备，字段键本身不携带设备身份。']),
('删除和注销',[
'null 只删除一个字段，解绑清该设备该来源，注销设备清所有来源，注销来源清所有设备对应数据。Registry 负责定义与绑定，StateStore 负责实时值，Receiver 组合两者。']),
('刷新路径',[
'Registry 和 StateStore 通知可来自后台，控制器合并到主线程。浮窗按已选字段查定义，再确定唯一设备，最后读值与格式化。没有唯一匹配设备时显示缺失，不随机选取。'])], [BASE+'data/receiver/DebugDataReceiverImpl.kt',BASE+'data/state/DebugStateStore.kt',BASE+'data/registry/DebugDataRegistry.kt',BASE+'ui/floating/FloatingWindowController.kt'],kind='pdf')

add(26,'现场导出与系统分享流程图解',
'图解按当前代码组织导出流程，区分文件生成、系统分享和实际接收。时间区间、相机日志和性能历史 CSV 属于二期扩展，不在当前流程中。',[
('当前导出',[
'用户勾选五类内容，页面读取选择并禁止重复操作，在 IO 调度器创建 ZIP。App 日志为可读文件中最后修改的一份；状态为最近快照。无日志而明确选中 App 日志时失败。']),
('产物与分享',[
'ZIP 使用 debug_summary.txt、camera_status.txt 和 app_log 目录。生成异常时尝试移除未完成文件，成功后清理更旧 ZIP 并保留最近五份。FileProvider 创建 content URI，系统 chooser 转交给接收 App。']),
('成功的边界',[
'ZIP 创建成功与目标 App 保存成功分开判断。现有页面没有接收方完成确认，也没有分享取消后立即清理产物的逻辑；保留规则应按实际代码理解。'])], [BASE+'data/export/DebugExportManager.kt',BASE+'ui/export/DebugLogExportActivity.kt','business/debug/debug_impl/src/main/res/xml/debug_file_paths.xml'],kind='pdf')

add(27,'Debug 二期目标架构与能力流程',
'本篇所有架构图表示二期目标，用于说明宿主适配、多设备、导出和高级诊断的职责边界。已有局部实现不等于整张图已落地。',[
('宿主与 SDK',[
'Live、Start 或其他宿主提供设备状态、运行参数和业务能力，通过各自 Adapter 转为统一模型。SDK 内部管理注册、状态、用例和展示；宿主没有提供的能力应隐藏或禁用。']),
('导出和运行状态',[
'统一导出任务汇集时间区间内 App 日志、固件支持的相机日志、性能采样记录，以及导出时的最新应用设备快照。每类来源返回成功、缺失或失败，最后按明确策略决定是否生成产物。']),
('交互和高级调试',[
'浮窗状态包括关闭、展开、折叠，拖动接近边缘才触发吸附。连接诊断观察已有宿主流程，固件通信 Mock 需要规则匹配与真实链路的明确边界。',
'当前方案尚需确认运行参数来源、相机日志接口、Mock 注入点、权限和跨 App 资源依赖。未确定部分不编造接口签名或协议编号。'])], [BASE+'DebugDependencies.kt',BASE+'domain/provider/DebugDataProvider.kt',BASE+'data/state/DebugStateStore.kt'],kind='pdf')

add(28,'一期现状与二期迁移对照',
'本篇把用户提供的一期与二期方案对照当前源码，列出实施差距和验收证据要求。状态以当前提交为边界，历史完成表不替代当前构建结果。',[
('实施次序',[
'先对齐 API 类型归属与初始化契约，再接通宿主数据来源和相机迁移；随后统一页面字段和多设备选择，再扩展运行参数、导出、诊断与跨 App。',
'能力矩阵同时记录实现状态和验证状态，允许一项功能“已有局部代码但未运行验收”。避免使用一个已完成标签覆盖多个不同阶段。']),
('验收证据',[
'功能保留实际操作结果与数据检查，构建隔离保留依赖及 APK 内容，跨 App 保留各宿主独立构建与接入记录，效率保留固定任务基线和测量样本。',
'用户方案给出的日期和工作日保留为历史计划。具体排期需在固件接口、设备和构建环境可用后确认，不根据源码文件数量重新承诺完成日期。'])], [BASE+'DebugRuntime.kt',BASE+'data/export/DebugExportManager.kt',BASE+'ui/main/DebugActivity.kt','app/build.gradle'],kind='pdf')

add(29,'相机字段标签与格式化参考',
'本参考按当前 CameraDebugFormatter 和 CameraDebugSnapshot 整理字段身份、显示标签、值表达式与格式化调用。用于开发回查，不作为固件协议物理单位或完整枚举规范。',[
('阅读规则',[
'字段 ID 属于详情展示层稳定身份，值表达式指向快照属性；它们不自动等于新 Registry 的 sourceId 与 fieldId。字段存在于详情 Formatter，也不表示已在通用浮窗注册。',
'格式化为整数的温度、电压、状态不补写未核实单位。未知版本和无效 Dev 数据按 Mapper 规则处理。名称单独查询、身份尾号与完整复制文本的区别详见相机身份说明。']),
('四组状态',[
'媒体组包含直接模式、开机模式和录像状态；设备组包含系统、蓝牙、版本、电池和连接；能力组当前两项；路由组当前四项。正文附上从源码核对提取的字段表和快照模型成员表。'])], [BASE+'ui/cmera/CameraDebugFormatter.kt',BASE+'CameraDebugSnapshot.kt',BASE+'CameraDebugSnapshotMapper.kt'],kind='pdf')
