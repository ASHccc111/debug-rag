import json, re, hashlib, textwrap, shutil, os, subprocess
from pathlib import Path
from html import escape
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.pagesizes import A4
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from corpus import DOCS, ROOT, BASE, API, BRANCH, COMMIT

OUT=Path('D:/code/debug-rag/note'); TMP=Path(__file__).parent
for p in [OUT/'docx',OUT/'pdf',TMP/'qa',TMP/'render']:
    p.mkdir(parents=True,exist_ok=True)
FONT='C:/Windows/Fonts/msyh.ttc'
pdfmetrics.registerFont(TTFont('CN',FONT,subfontIndex=0))
pdfmetrics.registerFont(TTFont('CNB','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
ST={
 'title':ParagraphStyle('title',fontName='CNB',fontSize=21,leading=29,spaceAfter=14,textColor=colors.black),
 'h':ParagraphStyle('h',fontName='CNB',fontSize=13,leading=19,spaceBefore=13,spaceAfter=7,keepWithNext=True,textColor=colors.black),
 'body':ParagraphStyle('body',fontName='CN',fontSize=10,leading=16,spaceAfter=7,wordWrap='CJK'),
 'small':ParagraphStyle('small',fontName='CN',fontSize=8,leading=12,spaceAfter=4,wordWrap='CJK'),
 'cell':ParagraphStyle('cell',fontName='CN',fontSize=8.5,leading=12,wordWrap='CJK'),
}

def p(text,style='body'):
    # Invisible break opportunities avoid overlong path/symbol strings in PDF only.
    text=escape(str(text))
    text=re.sub(r'([/_.])',r'\1<wbr/>',text)
    text=text.replace('\n','<br/>')
    return Paragraph(text,ST[style])

def table(headers,rows,width=477):
    n=len(headers)
    if n==2: widths=[width*.28,width*.72]
    elif n==3: widths=[width*.25,width*.30,width*.45]
    elif n==4: widths=[width*.24,width*.25,width*.25,width*.26]
    else: widths=[width/n]*n
    data=[[p(x,'cell') for x in headers]]+[[p(x,'cell') for x in row] for row in rows]
    t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DCE6EF')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#D9D9D9')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    return t

def source_records(doc):
    records=[]
    for rel in doc['sources']:
        path=ROOT/rel
        if not path.exists(): raise RuntimeError('Missing source '+rel)
        txt=path.read_text(encoding='utf-8-sig')
        if rel.endswith('.kt'):
            syms=re.findall(r'^\s*(?:(?:internal|private|public|data|sealed|abstract|enum|override|suspend|open)\s+)*(?:class|object|interface|fun)\s+([\w.]+)',txt,re.M)
        else: syms=[]
        records.append((rel,hashlib.sha256(path.read_bytes()).hexdigest()[:16],list(dict.fromkeys(syms))))
    return records

def field_rows():
    txt=(ROOT/(BASE+'ui/cmera/CameraDebugFormatter.kt')).read_text(encoding='utf-8')
    rows=[]
    for m in re.finditer(r'field\(\s*id\s*=\s*"([^"$]+)"\s*,\s*label\s*=\s*"([^"]+)"\s*,\s*value\s*=\s*([^\n]+)',txt):
        rows.append([m[1],m[2],m[3].rstrip(',')])
    for m in re.finditer(r'\bfield\(\s*"([^"$]+)"\s*,\s*"([^"]+)"\s*,\s*([^\n]+)',txt):
        rows.append([m[1],m[2],m[3].rstrip(',')])
    for m in re.finditer(r'addConnectionField\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(status\.\w+)',txt):
        rows.append(['dev.connection.'+m[1],'Connect / '+m[2],'formatBoolean('+m[3]+')'])
    for m in re.finditer(r'id\s*=\s*"((?:capability|router)\.[^"$]+)"\s*,\s*label\s*=\s*"([^"]+)"\s*,\s*value\s*=\s*([^\n]+)',txt):
        rows.append([m[1],m[2],m[3].rstrip(',')])
    seen=set()
    return [r for r in rows if not (r[0] in seen or seen.add(r[0]))]

def model_rows():
    txt=(ROOT/(BASE+'CameraDebugSnapshot.kt')).read_text(encoding='utf-8')
    rows=[]; current=''
    for line in txt.splitlines():
        cm=re.search(r'data class (\w+)',line)
        if cm: current=cm[1]
        vm=re.search(r'val (\w+):\s*([^,=]+)',line)
        if vm: rows.append([current,vm[1],vm[2].strip()])
    return rows

def addtable(n,title,headers,rows):
    DOCS[n]['tables'].append((title,headers,rows))

addtable(0,'专题目录',['编号与资料','格式与阅读用途'],[[f"{d['n']:02d} {d['title']}",d['kind'].upper()+'  '+('图解或参考' if d['kind']=='pdf' else '专题说明')] for d in DOCS])
capabilities=[
 ['主面板与热区','已有实现','界面与状态同步需构建后验证'],['手机性能采集','已有实现','约一秒快照 无历史记录'],['相机详情与复制','已有实现','单份最近快照'],['通用设备字段','局部接入','手机来源接通 相机迁移未闭合'],['展示配置','局部接入','浮窗已连接 内存保存'],['连接诊断与固件通信','占位入口','点击开发中'],['时间区间与相机日志','二期目标','接口与来源待确认'],['性能 CSV 与浮窗折叠吸边','二期目标','无当前完整实现证据'],['Flavor 隔离','配置存在','APK 与 CI 待本轮核验'],['跨 App 复用','二期目标','未核对 Start 仓库'],['初始化契约','静态不一致','先对齐 API 类型和方法签名']]
addtable(1,'能力与状态',['能力','实现状态','当前限制'],capabilities)
addtable(6,'通用性能字段',['字段 ID','数据来源','显示与缺失规则'],[
 ['cpu','PerformanceSnapshot.cpuPercent','NUMBER 单位 % 按核心数归一化'],['memory_pss','totalPssMb','NUMBER MB 采集失败当前可能为 0'],['fps','fps','NUMBER App 帧回调频率'],['battery_temperature','batteryTemperatureCelsius','NUMBER 摄氏度 null 删除旧值'],['java_heap','javaHeapMb','NUMBER MB Java 已用堆'],['native_heap','nativeHeapMb','NUMBER MB Native 分配量']])
fr=field_rows(); mr=model_rows()
for n,prefix in [(8,'media.'),(9,'dev.system.'),(10,'dev.version.')]:
    rows=[r for r in fr if r[0].startswith(prefix)]
    if rows:addtable(n,'相关显示字段',['显示 ID','标签','取值与格式化'],rows)
addtable(12,'接收入口与前置条件',['操作','前置条件','结果'],[
 ['registerDevice','稳定设备 ID','增加或更新设备'],['registerSource','稳定来源 ID','增加或更新来源'],['registerFields','来源已注册','按字段 ID 更新定义'],['bindSource','设备与来源都存在','建立设备来源关联'],['updateFields','来源已绑定设备','批量更新 null 删除'],['unbindSource','已有绑定','清值再解绑'],['unregisterDevice','指定设备','清设备值并移除设备'],['unregisterSource','指定来源','清所有设备该来源并移除定义']])
addtable(14,'展示目标与数量',['目标','最大字段数','实现说明'],[['MAIN_PANEL','12','枚举存在 页面统一配置需确认'],['FLOATING_WINDOW','8','已接通选择器与读取'],['DETAIL_PAGE','不限制','不代表详情已迁到通用模型']])
addtable(17,'ZIP 组成',['条目','来源','限制'],[['debug_summary.txt','选中应用 账号设备 性能','生成时现场快照'],['camera_status.txt','最新相机快照格式化','不是相机固件日志'],['app_log/原文件名','最后修改的可读 App 日志','不是指定时间范围集合']])
addtable(21,'目标保留变体',['变体','Debug 依赖','当前证据'],[['withDebugDebug','API 与 Impl','Gradle 配置'],['withDebugStaging','API 与 Impl','Gradle 配置'],['withoutDebugRelease','不走 withDebugImplementation','需检查实际 APK'],['withDebugRelease','被过滤','beforeVariants 配置'],['withoutDebugDebug 或 Staging','被过滤','beforeVariants 配置']])
addtable(22,'建议验收记录',['项目','证据','当前结果'],[['API 与初始化','类型可见性 服务实现 编译日志','待修正后执行'],['相机与多设备','设备事件与 UI 录屏','待执行'],['导出与分享','ZIP 条目 文件内容 URI','待执行'],['构建隔离','依赖图 APK CI 记录','待执行'],['Start 接入','Start 构建与设备结果','待执行'],['效率评估','固定任务 基线 样本数','未测量']])
addtable(28,'现状与目标',['主题','当前代码','二期目标'],[['设备状态','单相机快照与通用存储并行','按设备统一状态和选择'],['运行参数','性能和相机选定状态','编码 分辨率 音视频码率'],['配置','内存浮窗字段选择','各页面统一配置'],['日志','最新 App 日志与快照 ZIP','区间 相机日志 性能历史'],['浮窗','应用内拖动 位置恢复','折叠 近边吸附'],['测试清理','未形成目标统一入口','SDK 与宿主明确范围'],['诊断与 Mock','开发中入口','观察时间线与规则响应'],['宿主适配','Provider 契约 部分旧依赖','Live Adapter 和 Start 验证'],['初始化','静态签名不一致','类型公开边界与实现对齐']])
for prefix,title in [('media.','媒体显示字段'),('dev.system.','系统显示字段'),('dev.bluetooth.','蓝牙显示字段'),('dev.version.','版本显示字段'),('dev.battery.','电池显示字段'),('dev.connection.','连接显示字段'),('capability.','能力显示字段'),('router.','路由显示字段')]:
    subset=[r for r in fr if r[0].startswith(prefix)]
    if subset:addtable(29,title,['显示 ID','显示标签','值表达式'],subset)
addtable(29,'只读快照成员',['模型','成员','Kotlin 类型'],mr)
addtable(29,'格式化与缺失规则',['函数','实际规则'],[
 ['formatBoolean','true 显示是 false 显示否'],['formatInt','原始整数转字符串 不添加物理单位'],['formatDuration','非负数添加秒 负数显示 --'],['formatPercent','非负数添加 % 负数显示 -- 当前不限制大于 100'],['formatRecordState','0 Idle 1 Starting 2 Running 3 Stopping 其他保留未知原值'],['formatVersionRaw','null 显示 -- 其他十进制加八位十六进制'],['formatMacAddress','空列表显示 -- 每字节与 0xFF 后按两位十六进制连接'],['formatIdentityTail','SN 优先 无 SN 时 uniKey 取后四位']])
DOCS[4]['sources'].append(BASE+'DebugIdentity.kt')
DOCS[12]['sources'] += [BASE+'domain/model/DebugDevice.kt',BASE+'domain/model/DebugDataSource.kt',BASE+'domain/model/DebugFieldKey.kt']
DOCS[4]['sections'].insert(2,('账号设备身份读取',[
 'DebugIdentity.deviceId 通过 lazy 缓存 SystemUtils.queryMobileId 的结果；currentUserId 每次从 SPStoreManager 的当前用户对象读取 user_id。性能快照保存当次 UID 和 DID，未登录或缺失时显示相应占位。',
 '这条链路仍使用宿主通用用户模型和持久化工具，并非所有账号环境信息都已由 Adapter 注入。设备身份的生成语义由 SystemUtils 所有者负责，本篇不把它等同于硬件 SN。']))
DOCS[17]['sections'][2][1].append('debug_summary.txt 在 ZIP 中总会创建；用户选项决定摘要中的具体信息段。即使只选择日志，也会有这份说明条目。相机无快照时管理器生成相应无数据说明，不能据文件存在就认定已采集成功。')
DOCS[14]['sections'][2][1].append('整组勾选先构造完整候选，再检查八项上限；超限时不改变当前选择，不会悄悄只加入组内前几项。取消整组选中则移除该组所有选项。')

# Preserve provenance for every production Kotlin file without dumping source code.
all_kt=sorted((ROOT/'business/debug').rglob('*.kt'))
coverage=[]
for src in all_kt:
    rel=src.relative_to(ROOT).as_posix()
    matched=[f"{d['n']:02d}" for d in DOCS if rel in d['sources']]
    coverage.append([src.name,', '.join(matched) or '见模块说明及源码回查',rel.replace('business/debug/debug_impl/src/main/java/com/obsbot/live/business/debug/','Impl / ').replace('business/debug/debug_api/src/main/java/com/obsbot/live/business/debug/','API / ')])
addtable(0,'生产 Kotlin 文件覆盖索引',['文件','专题编号','相对位置'],coverage)

FLOW={
24:[('当前装配与调用边界',['App withDebug 初始化','DebugFeature 与 IDebugService','DebugServiceImpl 契约待对齐','DebugRuntime 组件装配','采集器 注册存储 页面控制器']),('旧相机快照路径',['CameraBigPushEvent','StatusManager 查询 Handle','Mapper 复制 Snapshot','Monitor.latestSnapshot','主面板 详情 复制 相机导出']),('通用性能字段路径',['AppPerformanceMonitor','PhonePerformanceSource','Receiver 绑定检查','StateStore 与 Registry','FloatingWindowController','按设备读取并主线程展示'])],
25:[('注册与更新',['registerDevice 与 registerSource','registerFields','bindSource','updateFields 检查绑定','StateStore 按设备来源保存','通知并合并主线程刷新']),('清理与展示',['null 删除单字段','解绑清指定设备来源','注销设备清所有来源','注销来源清所有设备','选择字段并解析唯一设备','缺失或类型不符显示占位'])],
26:[('当前导出主流程',['选择五类现场内容','空选择阻止生成','IO 线程读取日志与快照','写摘要 相机文本 日志到 ZIP','异常删除未完成 ZIP','成功保留最近五份']),('系统分享与结果边界',['创建 FileProvider content URI','ACTION_SEND 与读取授权','打开系统分享选择器','接收 App 处理文件','当前无接收方保存确认','取消分享无立即删除回调'])],
27:[('目标宿主适配架构',['Live Start 其他宿主业务','各宿主 Adapter 转换数据','统一设备 字段 能力契约','Domain 用例与按设备状态','Data 通用采集及宿主适配','UI 按能力与设备展示']),('目标统一导出',['时间范围与内容选择','App 日志 相机日志 性能历史','最新应用与设备状态快照','统一结果与部分失败检查','符合策略生成 ZIP 或 CSV','保存或系统分享']),('目标高级调试',['宿主真实连接与通信链路','连接事件观察 或 指令规则匹配','阶段时间线 或 真实与 Mock 响应','耗时 异常 执行记录','原业务响应处理不重复实现'])],
28:[('建议迁移次序',['对齐公开契约与初始化','接通宿主 Provider','按设备迁移相机数据','统一字段选择与各页面','扩展导出 交互与高级诊断','Live 回归与 Start 接入验证'])]
}
FLOW[25][1]=('独立清理操作与读取边界',[])
FLOW[26][0]=('当前导出成功路径',['读取五类内容选择','校验非空 失败则停止','IO 读取所选日志与快照','写 ZIP 失败则进入异常处理','成功清理旧 ZIP 保留五份','返回 ZIP 文件供系统分享'])
FLOW[26][1]=('系统分享交接',['创建 FileProvider content URI','ACTION_SEND 与读取授权','启动系统分享选择器','用户选择接收应用或取消'])
FLOW[27][0]=('目标数据接入与展示',['Live Start 其他宿主业务','各宿主 Adapter 转换数据','统一设备 字段 能力契约','Data 来源接入与状态存储','Domain 用例与状态选择','UI 按能力与设备展示'])

def diagram(title,labels):
    width=477; bh=43; gap=21; h=35+len(labels)*(bh+gap)
    drawing=Drawing(width,h)
    drawing.add(String(0,h-14,title,fontName='CNB',fontSize=11,fillColor=colors.black))
    bw=365; x=(width-bw)/2
    for i,label in enumerate(labels):
        y=h-40-(i+1)*bh-i*gap
        drawing.add(Rect(x,y,bw,bh,rx=5,ry=5,fillColor=colors.HexColor('#EDF3F8' if i%2==0 else '#F3F5F4'),strokeColor=colors.HexColor('#7C8B98'),strokeWidth=.7))
        drawing.add(String(width/2,y+16,label,fontName='CN',fontSize=10,textAnchor='middle'))
        if i<len(labels)-1:
            drawing.add(Line(width/2,y,width/2,y-gap+4,strokeColor=colors.HexColor('#526477')))
            drawing.add(Polygon([width/2-4,y-gap+7,width/2+4,y-gap+7,width/2,y-gap],fillColor=colors.HexColor('#526477'),strokeColor=None))
    return drawing

def footer(canvas,doc):
    canvas.setFont('CN',8);canvas.setFillColor(colors.HexColor('#666666'))
    canvas.drawString(42,24,'OBSBOT Live Debug 技术资料  2026 年 11 月 3 日')
    canvas.drawRightString(A4[0]-42,24,str(doc.page))

def build_pdf(doc,path):
    story=[p(doc['title'],'title'),p(doc['intro']),p('版本范围  '+BRANCH+'  '+COMMIT[:12]+'  |  '+('二期目标设计' if doc['n'] in [23,27] else '当前实现与明确标注的待办'),'small')]
    for heading,paras in doc['sections']:
        story.append(p(heading,'h'))
        story.extend(p(t) for t in paras)
    for title,labels in FLOW.get(doc['n'],[]):
        story.append(PageBreak())
        if doc['n']==25 and not labels:
            story += [p(title,'h'),table(['独立操作','清理范围'],[['null 字段更新','删除一台设备一个来源中的单个值'],['unbindSource','清一台设备一个来源并解除绑定'],['unregisterDevice','清一台设备全部来源并注销设备'],['unregisterSource','清全部设备对应来源并删除定义']]),Spacer(1,14),diagram('按当前状态读取',['选择 sourceId 与 fieldId','核对字段定义与设备绑定','解析唯一设备并读 StateStore','缺失或类型不符显示占位'])]
        else:story.append(diagram(title,labels))
        if doc['n']==26:
            story += [p('异常与结果边界','h'),p('空选择和选中但无 App 日志都会停止生成；写 ZIP 异常时尝试删除未完成文件并返回失败。分享取消没有立即删除产物的回调；当前未确认接收 App 是否最终保存。')]
        story += [Spacer(1,9),p('图示须结合正文状态说明阅读。标为目标的流程不代表当前已实施；当前源码图不替代编译和运行验证。','small')]
    for title,headers,rows in doc['tables']:
        story += [p(title,'h'),table(headers,rows),Spacer(1,9)]
    story += [p('源码依据与版本回查','h'),p('统一基线提交 '+COMMIT+'。以下摘要为文件 SHA256 前 16 位，用于核对资料整理时的源码版本。','small')]
    for rel,digest,syms in source_records(doc):
        story += [p(rel,'small'),p('摘要 '+digest+'；主要符号 '+('、'.join(syms[:12]) or '配置或资源文件'),'small')]
    if doc['n'] in [23,27,28]:
        story.append(p('设计依据另包括用户提供的 Debug 一期现状与二期技术建设方案及配图。方案中的历史状态、工期估计和目标与当前源码分别理解。','small'))
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=43,title=doc['title'],author='').build(story,onFirstPage=footer,onLaterPages=footer)

def cell_format(cell,header=False):
    cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    tcPr=cell._tc.get_or_add_tcPr()
    margins=OxmlElement('w:tcMar')
    for key in ['top','left','bottom','right']:
        el=OxmlElement('w:'+key);el.set(qn('w:w'),'95');el.set(qn('w:type'),'dxa');margins.append(el)
    tcPr.append(margins)
    if header:
        sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'DCE6EF');tcPr.append(sh)
    for para in cell.paragraphs:
        para.paragraph_format.space_after=Pt(3)
        for run in para.runs:
            run.font.size=Pt(9)
            if header:run.bold=True

def docx_table(d,headers,rows):
    t=d.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    ratios={2:[.28,.72],3:[.25,.30,.45]}.get(len(headers),[1/len(headers)]*len(headers))
    for col,ratio in zip(t.columns,ratios):col.width=Cm(17*ratio)
    for i,val in enumerate(headers):
        t.rows[0].cells[i].text=str(val);t.rows[0].cells[i].width=Cm(17*ratios[i]);cell_format(t.rows[0].cells[i],True)
    rep=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(rep)
    for row in rows:
        cells=t.add_row().cells
        for i,val in enumerate(row):cells[i].text=str(val);cells[i].width=Cm(17*ratios[i]);cell_format(cells[i])
    borders=OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        el=OxmlElement('w:'+edge)
        for k,v in [('val','single'),('sz','4'),('color','D9D9D9')]:el.set(qn('w:'+k),v)
        borders.append(el)
    t._tbl.tblPr.append(borders)
    d.add_paragraph()

def build_docx(doc,path):
    d=Document();sec=d.sections[0]
    sec.page_height=Cm(29.7);sec.page_width=Cm(21);sec.top_margin=Cm(1.9);sec.bottom_margin=Cm(1.8);sec.left_margin=Cm(2);sec.right_margin=Cm(2)
    for name,size in [('Normal',10.5),('Title',21),('Heading 1',13),('Heading 2',11.5)]:
        s=d.styles[name];s.font.name='Microsoft YaHei';s.font.size=Pt(size);s.font.color.rgb=RGBColor(0,0,0)
        s.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'微软雅黑')
        s.paragraph_format.line_spacing=1.25;s.paragraph_format.space_after=Pt(6)
    d.styles['Title'].paragraph_format.space_after=Pt(13)
    d.styles['Heading 1'].paragraph_format.space_before=Pt(10)
    ss=d.styles.add_style('SourceReference',1);ss.base_style=d.styles['Normal'];ss.font.size=Pt(8.5)
    ss.paragraph_format.space_after=Pt(5);ss.paragraph_format.keep_together=True
    d.add_paragraph(doc['title'],'Title');d.add_paragraph(doc['intro'])
    d.add_paragraph('适用分支 '+BRANCH+'\n基线提交 '+COMMIT+'\n资料日期 2026 年 11 月 3 日')
    for heading,paras in doc['sections']:
        d.add_heading(heading,level=1)
        for para in paras:d.add_paragraph(para)
    for title,headers,rows in doc['tables']:
        d.add_heading(title,level=1);docx_table(d,headers,rows)
    d.add_heading('源码依据与版本回查',level=1)
    d.add_paragraph('以下路径相对于 OBSBOT_Live 仓库。Impl 表示 business/debug/debug_impl/src/main/java/com/obsbot/live/business/debug，API 表示对应 debug_api 源码根。摘要为文件 SHA256 前 16 位。','SourceReference')
    for rel,digest,syms in source_records(doc):
        short=rel.replace(BASE,'Impl/').replace(API,'API/')
        d.add_paragraph(short+'\n摘要 '+digest+'；符号 '+('、'.join(syms[:6]) or '配置或资源文件'),'SourceReference')
    if doc['n']==23:d.add_paragraph('设计依据另包括用户提供的 Debug 一期现状与二期技术建设方案及配图。以上目标不作为当前源码已完成的声明。')
    footerp=sec.footer.paragraphs[0];footerp.alignment=2
    run=footerp.add_run('OBSBOT Live Debug  ');run.font.size=Pt(8)
    fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');footerp._p.append(fld)
    d.core_properties.title=doc['title'];d.core_properties.author='';d.core_properties.subject='Debug 技术资料';d.save(path)

def docx_preview(path,out):
    """OOXML content layout fallback, not native Word pagination."""
    d=Document(path);story=[]
    for child in d.element.body:
        tag=child.tag.rsplit('}',1)[-1]
        if tag=='p':
            text=''.join(child.itertext())
            # itertext includes run child duplication in python-docx objects; use Paragraph.text
            from docx.text.paragraph import Paragraph as DP
            obj=DP(child,d);text=obj.text
            if not text:continue
            name=obj.style.name
            story.append(p(text,'title' if name=='Title' else 'h' if name.startswith('Heading') else 'small' if name=='SourceReference' else 'body'))
        elif tag=='tbl':
            from docx.table import Table as DT
            tab=DT(child,d);rows=[[c.text for c in r.cells] for r in tab.rows]
            if rows:story += [table(rows[0],rows[1:]),Spacer(1,8)]
    SimpleDocTemplate(str(out),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=43).build(story,onFirstPage=footer,onLaterPages=footer)

def main():
    manifest=[]
    for doc in DOCS:
        name=f"{doc['n']:02d}_{doc['title']}.{doc['kind']}"
        target=OUT/doc['kind']/name
        if doc['kind']=='docx':
            build_docx(doc,target)
            docx_preview(target,TMP/'qa'/f"{doc['n']:02d}_preview.pdf")
        else:build_pdf(doc,target)
        manifest.append({'number':doc['n'],'title':doc['title'],'format':doc['kind'],'path':str(target),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'sources':source_records(doc)})
        print(f"created {doc['n']:02d} {doc['kind']}",flush=True)
    (TMP/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (TMP/'content.json').write_text(json.dumps(DOCS,ensure_ascii=False,indent=2),encoding='utf-8')
    print('fields',len(fr),'model-members',len(mr),'documents',len(DOCS))

if __name__=='__main__':main()
