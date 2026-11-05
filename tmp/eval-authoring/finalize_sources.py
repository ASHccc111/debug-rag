import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
W=Path(__file__).parent;O=Path(json.loads((W/'paths.json').read_text(encoding='utf-8'))['output'])
read=lambda f:json.loads(f.read_text(encoding='utf-8'))
blocks=list(map(json.loads,(O/'source_blocks.jsonl').read_text(encoding='utf-8').splitlines()))
blocks=[b for b in blocks if not (b['doc_id']=='DOC-00' and int(b['block_id'][-6:])>=82)]
(O/'source_blocks.jsonl').write_text(''.join(json.dumps(b,ensure_ascii=False)+'\n' for b in blocks),encoding='utf-8')
bm={b['block_id']:b for b in blocks}
da=read(W/'docx-audit.json')
for entry in da:
 n=sum(b['doc_id']==entry['doc_id'] for b in blocks)
 entry['block_count']=n;entry['python_docx_location_text_matches']=n
(W/'docx-audit.json').write_text(json.dumps(da,ensure_ascii=False,indent=2),encoding='utf-8')
m=read(O/'corpus_manifest.json');issues=[]
notes={
24:(16,'PDF 第2至4页为节点与箭头图。正文已给出当前入口及两条数据路径；本次关系题仅使用第1页明确正文，不以节点提取顺序推导依赖或完成状态。'),
25:(23,'PDF 第1页部分正文在“相同”“Registry 负”“最后”处发生视觉换行，原文块按行保留；第3页独立清理表保持原单元格 bbox。跨行事实使用多个连续片段，不拼造 quote。'),
26:(23,'PDF 第2页异常边界在“立即删”后换行。原始两行均保留；所选证据只截取前一行完整表达的停止/失败规则。生成成功与分享完成分开标注。'),
27:(18,'PDF 第2至4页均为二期目标图。只把正文和节点作为设计说明，未将箭头或统一模型存在解释成已经接入/验收。接口签名及协议编号未补写。'),
28:(25,'PDF 第2页“现状与目标”表已按实际网格提取。列标题分别为当前代码、二期目标；所选日志题保持同一行对应，不把目标列合并为现状。'),
29:(29,'PDF 第1页表格内 media.boot.main_work_mode 视觉断行为 media.boot.main_work_m / ode；其他长 ID/类型/表达式同样有单元格内换行。保留原始 LF，不静默重建标识符；本次确切标识符题选择无断行单元格。完整原始表保留行列 bbox 供人工复核。')}
for d,(n,t) in notes.items():
 b=bm[f'DOC-{d:02d}-B{n:06d}'];i=dict(issue_id=f'ISSUE-{len(issues)+1:04d}',issue_type='pdf_extraction_boundary',affected_doc_ids=[b['doc_id']],affected_case_ids=[],details=t,source_locations=[dict(doc_id=b['doc_id'],locator=b['locator'])],blocking=False,required_resolution='人工逐题复核相关 PDF 原页与引用语义；长标识符如需重建须新记录 before/after 和视觉核对方法。本次没有依赖未核实重建内容。');issues.append(i)
for d in m['documents']:
 d['extraction_issues']=[dict(issue_id=i['issue_id'],details=i['details']) for i in issues if d['doc_id'] in i['affected_doc_ids']]
audit=dict(schema_version='1.0',performed_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),performed_by='generating_agent',human_review=False,scope='固定30份；正文、简单表格、图示节点；源码依据尾部除版本声明外排除。',docx=read(W/'docx-audit.json'),pdf=read(W/'pdf-audit.json'),visual_inspection=dict(method='从当前哈希原件由 Poppler 渲染全部29页，逐份查看6组共7张联系表；字段表行列、换行和图示布局与文字提取交叉核对。',render_page_count=29,diagram_policy='关系/顺序题有明确正文或已核对的节点与箭头来源；不将目标图当当前代码。',limitations='联系表用于整体核对；人工审核仍需放大原页逐题检查。PDF 原始断行保留，未做静默字段重建。'),source_code_crosscheck='not_available',source_code_note='当前工作区未提供对应业务提交；未读取工作区外业务源码。',reading_complete=True,unread_parts=[],known_unresolved_content_conflicts=[])
(O/'extraction_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(O/'corpus_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(O/'review_queue.jsonl').write_text(''.join(json.dumps(i,ensure_ascii=False)+'\n' for i in issues),encoding='utf-8')
print('Recorded source reading audit and six nonblocking PDF boundaries.')
