"""Offline draft checks. No network, indexing, RAG execution or human approval.

This implements the closed contracts used by this dataset, NOT a general JSON
Schema implementation. PDF checks reuse the already installed pdfplumber.
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
from xml.etree import ElementTree as ET

TOPICS=['overview_initialization','phone_performance','camera','registry_state','field_selection_overlay','hotspot_detection','export_share','host_build_maintenance','phase2_verification']
DEV={'fact':10,'operation':10,'cross_document':6,'status':7,'boundary:insufficient_evidence':3,'boundary:out_of_scope':2,'boundary:clarify':2}
TOTAL={'fact':15,'operation':15,'cross_document':10,'status':10,'boundary:insufficient_evidence':4,'boundary:out_of_scope':3,'boundary:clarify':3}
TITLES=['Debug 技术资料导读与版本范围','Debug 当前能力与功能边界','Debug 入口 SPI 与初始化契约','Debug 运行时装配与资源生命周期','Debug 主面板与测试环境操作','手机性能采样机制与指标解释','手机性能数据源与通用字段','相机状态事件采集与快照转换','相机媒体模式与录像状态说明','相机系统电池与设备身份说明','相机版本连接标记与能力说明','相机详情页面与文本复制','设备数据源字段注册与接收契约','实时状态缓存与并发通知','展示字段配置与选择交互','应用内悬浮窗行为与生命周期','可操作控件热区检测','现场数据收集与 ZIP 组织','导出页面系统分享与失败处理','宿主能力适配与跨 App 接入边界','Debug 扩展维护与问题定位','Flavor 编译隔离与构建核验','Debug 验证计划与验收记录要求','Debug 二期建设目标与实施约束','Debug 当前架构与调用关系图解','设备字段更新与悬浮窗刷新图解','现场导出与系统分享流程图解','Debug 二期目标架构与能力流程','一期现状与二期迁移对照','相机字段标签与格式化参考']
EXPECTED={f'DOC-{i:02d}':f'{"docx" if i<24 else "pdf"}/{i:02d}_{t}.{"docx" if i<24 else "pdf"}' for i,t in enumerate(TITLES)}
SEED=20261104

def obj(props,**kw):
    return {'type':'object','required':list(props),'properties':props,'additionalProperties':False,**kw}
def arr(items,minimum=0,**kw):return {'type':'array','items':items,'minItems':minimum,**kw}
def st(pattern=None,**kw):return {'type':'string','minLength':1,**({'pattern':pattern} if pattern else {}),**kw}
def enum(*values):return {'enum':list(values)}
def nullable(s):return {'anyOf':[s,{'type':'null'}]}
ID=st(r'^DOC-\d{2}$');HASH=st(r'^[0-9a-f]{64}$');G=st(r'^G[1-9]\d*$');BID=st(r'^DOC-\d{2}-B\d{6}$')
INT={'type':'integer','minimum':1};BOOL={'type':'boolean'};STRINGS=arr(st())
LOC_DOCX=obj({'format':{'const':'docx'},'body_index':INT,'table_row':nullable(INT),'table_cell':nullable(INT),'paragraph_in_cell':nullable(INT)})
LOC_PDF=obj({'format':{'const':'pdf'},'page':INT,'bbox':arr({'type':'number'},4,maxItems=4)})
LOC={'anyOf':[LOC_DOCX,LOC_PDF]}
POINT=obj({'point_id':st(r'^P[1-9]\d*$'),'text':st(),'critical':BOOL,'required_literals':arr(st(),uniqueItems=True),'support_sets':arr(arr(G,1,uniqueItems=True),1,uniqueItems=True)})
EVIDENCE=obj({'evidence_id':G,'role':enum('support','scope','disambiguation'),'doc_id':ID,'source_sha256':HASH,'block_id':BID,'char_start':{'type':'integer','minimum':0},'char_end':INT,'quote':st()})
FORBIDDEN=obj({'claim':st(),'severity':enum('critical','major'),'reason':st(),'evidence_ids':arr(G,uniqueItems=True)})
ABSENCE=obj({'missing_information':st(),'checked_doc_ids':arr(ID,1,uniqueItems=True),'check_summary':st()})
INTERPRET=obj({'condition':st(),'answer_difference':st(),'evidence_ids':arr(G,1,uniqueItems=True)})
CLARIFY=obj({'missing_slot':st(),'acceptable_question_intent':st(),'example_question':st(),'interpretations':arr(INTERPRET,2,maxItems=2)})
REVIEW=obj({'machine_checked':BOOL,'human_status':enum('pending','approved','rejected'),'approved_by':nullable(st()),'approved_at':nullable(st(format='date-time')),'notes':STRINGS},allOf=[{'if':{'properties':{'human_status':{'const':'pending'}}},'then':{'properties':{'approved_by':{'type':'null'},'approved_at':{'type':'null'}}},'else':{'properties':{'approved_by':st(),'approved_at':st(format='date-time')}}}])

def case_schema():
    s=obj({'case_id':st(r'^DBG-EVAL-\d{4}$'),'split':enum('dev','test'),'family_id':st(),'category':enum('fact','operation','cross_document','status','boundary'),'topic':enum(*TOPICS),'question':st(maxLength=300),'expected_status':enum('answered','insufficient_evidence','out_of_scope','clarify'),'reference_answer':st(),'retrieval_scored':BOOL,'required_points':arr({'$ref':'#/$defs/point'}),'forbidden_claims':arr({'$ref':'#/$defs/forbidden'},1),'evidence':arr({'$ref':'#/$defs/evidence'}),'response_requirements':STRINGS,'absence_check':nullable({'$ref':'#/$defs/absence'}),'clarification':nullable({'$ref':'#/$defs/clarification'}),'review':{'$ref':'#/$defs/review'}})
    s.update({'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:debug-business-v1:case','title':'Debug business single-turn evaluation draft','description':'Closed case contract. Cross-file and semantic review requirements are additional.','allOf':[
      {'if':{'properties':{'expected_status':{'const':'answered'}}},'then':{'properties':{'category':enum('fact','operation','cross_document','status'),'retrieval_scored':{'const':True},'required_points':{'minItems':1},'evidence':{'minItems':1,'items':{'properties':{'role':{'const':'support'}}}},'response_requirements':{'maxItems':0},'absence_check':{'type':'null'},'clarification':{'type':'null'}}},'else':{'properties':{'category':{'const':'boundary'},'retrieval_scored':{'const':False},'required_points':{'maxItems':0},'response_requirements':{'minItems':1}}}},
      {'if':{'properties':{'expected_status':{'const':'insufficient_evidence'}}},'then':{'properties':{'absence_check':{'$ref':'#/$defs/absence'},'evidence':{'items':{'properties':{'role':{'const':'scope'}}}}}},'else':{'properties':{'absence_check':{'type':'null'}}}},
      {'if':{'properties':{'expected_status':{'const':'clarify'}}},'then':{'properties':{'clarification':{'$ref':'#/$defs/clarification'},'evidence':{'minItems':2,'items':{'properties':{'role':{'const':'disambiguation'}}}}}},'else':{'properties':{'clarification':{'type':'null'}}}},
      {'if':{'properties':{'expected_status':{'const':'out_of_scope'}}},'then':{'properties':{'evidence':{'maxItems':0}}}}
    ],'$defs':{'point':POINT,'evidence':EVIDENCE,'forbidden':FORBIDDEN,'absence':ABSENCE,'clarification':CLARIFY,'review':REVIEW}})
    return s

BLOCK=obj({'block_id':BID,'doc_id':ID,'source_sha256':HASH,'kind':enum('paragraph','heading','table_cell','diagram_text'),'section_path':STRINGS,'locator':LOC,'text':st(),'extraction_verified':BOOL,'reconstruction_notes':arr(obj({'before':st(),'after':st(),'reason':st(),'verification_method':st()}))})
ISSUE=obj({'issue_id':st(),'issue_type':st(),'affected_doc_ids':arr(ID),'affected_case_ids':arr(st(r'^DBG-EVAL-\d{4}$')),'details':st(),'source_locations':arr(obj({'doc_id':ID,'locator':nullable(LOC)})),'blocking':BOOL,'required_resolution':st()})
DOC=obj({'doc_id':ID,'file':st(),'title':st(),'format':enum('docx','pdf'),'sha256':HASH,'byte_size':INT,'page_count':nullable(INT),'declared_business_branch':nullable(st()),'declared_business_commit':nullable(st(r'^[0-9a-f]{40}$')),'declared_document_date':nullable(st(r'^\d{4}-\d{2}-\d{2}$')),'version_evidence':arr(obj({'block_id':BID,'quote':st()})),'source_code_crosscheck':enum('not_available','not_checked','matched','conflict'),'extraction_issues':arr({'type':'object'})})
MANIFEST=obj({'schema_version':{'const':'1.0'},'dataset_version':{'const':'debug-business-v1'},'dataset_status':enum('draft','incomplete'),'created_at':st(format='date-time'),'expected_document_count':{'const':30},'actual_document_count':{'type':'integer','minimum':0},'missing_files':STRINGS,'unreadable_files':STRINGS,'corpus_digest':HASH,'documents':arr(DOC),'extraction_environment':obj({'docx':st(),'pdf':st(),'pdf_coordinate_convention':st(),'source_code_note':st()})})

class DuplicateKey(ValueError):pass
def no_duplicate_keys(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise DuplicateKey('duplicate JSON key')
        d[k]=v
    return d

def digest(rows):
    rows=[{'doc_id':r['doc_id'],'sha256':r['sha256']} for r in sorted(rows,key=lambda x:x['doc_id'])]
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()

def contract(value,schema,root=None,path='$'):
    """Known contract keyword subset only; errors never include field values."""
    root=root or schema;errors=[]
    def bad(why):errors.append(path+': '+why)
    if '$ref' in schema:
        target=root
        for part in schema['$ref'][2:].split('/'):target=target[part]
        errors+=contract(value,target,root,path)
    if 'const' in schema and (type(value)!=type(schema['const']) or value!=schema['const']):bad('const mismatch')
    if 'enum' in schema and not any(type(value)==type(x) and value==x for x in schema['enum']):bad('enum mismatch')
    typ=schema.get('type');types={'object':dict,'array':list,'string':str,'boolean':bool,'integer':int,'null':type(None)}
    if typ:
        valid=(type(value) in [int,float] and not isinstance(value,bool)) if typ=='number' else type(value)==types[typ]
        if not valid:return errors+[path+': type mismatch']
    if 'anyOf' in schema and not any(not contract(value,s,root,path) for s in schema['anyOf']):bad('anyOf mismatch')
    for s in schema.get('allOf',[]):errors+=contract(value,s,root,path)
    if 'if' in schema:
        branch='then' if not contract(value,schema['if'],root,path) else 'else'
        if branch in schema:errors+=contract(value,schema[branch],root,path)
    if isinstance(value,dict):
        required=set(schema.get('required',[]));props=schema.get('properties',{})
        if required-value.keys():bad('missing fields: '+','.join(sorted(required-value.keys())))
        if schema.get('additionalProperties') is False and value.keys()-props.keys():bad('extra fields: '+','.join(sorted(value.keys()-props.keys())))
        for k,s in props.items():
            if k in value:errors+=contract(value[k],s,root,path+'.'+k)
    if isinstance(value,list):
        if len(value)<schema.get('minItems',0):bad('too few items')
        if len(value)>schema.get('maxItems',10**9):bad('too many items')
        if schema.get('uniqueItems') and len({json.dumps(x,sort_keys=True,ensure_ascii=False) for x in value})!=len(value):bad('duplicate array member')
        for i,x in enumerate(value):
            if 'items' in schema:errors+=contract(x,schema['items'],root,f'{path}[{i}]')
    if isinstance(value,str):
        if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',10**9):bad('string length')
        if 'pattern' in schema and re.search(schema['pattern'],value) is None:bad('pattern mismatch')
        if schema.get('format')=='date-time':
            try:
                dt=datetime.fromisoformat(value.replace('Z','+00:00'))
                if 'T' not in value or dt.tzinfo is None:bad('timezone-aware date-time required')
            except (ValueError,TypeError):bad('invalid date-time')
    if type(value) in [int,float] and value<schema.get('minimum',float('-inf')):bad('below minimum')
    return errors

def allocation(cases):
    grouped=defaultdict(list);result=[]
    for c in cases:
        key=c['category'] if c['category']!='boundary' else 'boundary:'+c['expected_status'];grouped[key].append(c)
    for key,rows in sorted(grouped.items()):
        rows.sort(key=lambda c:(hashlib.sha256(f'{SEED}:{c["family_id"]}'.encode('utf-8')).hexdigest(),c['family_id']))
        for i,c in enumerate(rows):result.append(dict(family_id=c['family_id'],stratum=key,rank=i+1,allocation_key=hashlib.sha256(f'{SEED}:{c["family_id"]}'.encode('utf-8')).hexdigest(),split='dev' if i<DEV.get(key,0) else 'test'))
    return result

def run(dataset,corpus,mark=False,write=True):
    errors=[];checks=[];bad_case=set()
    def fail(group,code,location,case_id=None):
        if not isinstance(case_id,str):case_id=None
        errors.append(dict(group=group,code=code,location=location,**({'case_id':case_id} if case_id else {})))
        if case_id:bad_case.add(case_id)
    def check(group,code,passed,location):
        if not passed:fail(group,code,location)
    def load(name,jsonl=False):
        path=dataset/name
        try:
            raw=path.read_bytes()
            if raw.startswith(b'\xef\xbb\xbf'):raise ValueError('BOM')
            txt=raw.decode('utf-8')
            if jsonl:
                rows=[]
                for i,line in enumerate(txt.splitlines(),1):
                    try:
                        if not line.strip():raise ValueError('blank JSONL line')
                        row=json.loads(line,object_pairs_hook=no_duplicate_keys,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                        if not isinstance(row,dict):raise ValueError('not object')
                        rows.append(row)
                    except (ValueError,TypeError):fail('A','jsonl_encoding_or_object',f'{name}:{i}')
                return rows
            value=json.loads(txt,object_pairs_hook=no_duplicate_keys,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if not isinstance(value,dict):raise ValueError('expected object')
            return value
        except (OSError,ValueError,UnicodeError):fail('A','file_encoding_or_json',name);return [] if jsonl else {}
    m=load('corpus_manifest.json');blocks=load('source_blocks.jsonl',True);issues=load('review_queue.jsonl',True)
    schema=load('dataset.schema.json');sm=load('split_manifest.json');audit=load('extraction_audit.json')
    casefiles={s:load(s+'.jsonl',True) for s in ['dev','test']};cases=sum(casefiles.values(),[])
    check('A','schema_contract_unchanged',schema==case_schema(),'dataset.schema.json')
    for s,rows in casefiles.items():
        for n,c in enumerate(rows,1):
            loc=f'{s}.jsonl:{n}';cid=c.get('case_id') if isinstance(c.get('case_id'),str) else loc
            for e in contract(c,case_schema()):fail('A','case_contract',loc+' '+e,cid)
            if c.get('split')!=s:fail('A','split_file_mismatch',loc,cid)
    for name,rows,spec in [('source_blocks.jsonl',blocks,BLOCK),('review_queue.jsonl',issues,ISSUE)]:
        for n,b in enumerate(rows,1):
            for e in contract(b,spec):fail('A','record_contract',f'{name}:{n} '+e)
    for e in contract(m,MANIFEST):fail('A','manifest_contract',e)
    check('A','manifest_version',m.get('schema_version')=='1.0' and m.get('dataset_version')=='debug-business-v1' and m.get('dataset_status') in ['draft','incomplete'],'corpus_manifest.json')
    for e in contract(m.get('created_at'),st(format='date-time')):fail('A','manifest_created_at',e)
    docs=m.get('documents',[])
    if not isinstance(docs,list):docs=[]
    dm={};native_docx={};native_pdf={};pdf_handles=[]
    for i,d in enumerate(docs):
        loc=f'corpus_manifest.json:documents[{i}]'
        ds=contract(d,DOC)
        for e in ds:fail('A','document_contract',loc+' '+e)
        if ds:continue
        did=d['doc_id']
        if did in dm:fail('A','duplicate_doc_id',did)
        dm[did]=d
        check('A','document_expected_mapping',EXPECTED.get(did)==d['file'],did)
        check('A','relative_source_path',not PurePosixPath(d['file']).is_absolute() and '\\' not in d['file'] and '..' not in PurePosixPath(d['file']).parts,did)
        check('A','document_format',d['file'].endswith('.'+d['format']) and (d['format']!='docx' or d['page_count'] is None),did)
        path=corpus/d['file']
        if not path.is_file():fail('B','source_file_missing',did);continue
        try:raw=path.read_bytes()
        except OSError:fail('B','source_file_unreadable',did);continue
        check('A','file_sha256',hashlib.sha256(raw).hexdigest()==d['sha256'],did)
        check('A','file_byte_size',len(raw)==d['byte_size'],did)
        try:
            if d['format']=='docx':
                with ZipFile(path) as z:native_docx[did]=ET.fromstring(z.read('word/document.xml')).find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body')
            else:
                import pdfplumber
                p=pdfplumber.open(path);pdf_handles.append(p);native_pdf[did]=p
                check('A','actual_pdf_page_count',len(p.pages)==d['page_count'],did)
        except Exception:fail('B','source_native_parse_unavailable',did)
        if d['source_code_crosscheck']=='matched':fail('A','matched_requires_separate_audit','documents:'+did)
    check('A','actual_document_count_consistency',type(m.get('actual_document_count')) is int and m.get('actual_document_count')==len(docs),'corpus_manifest.json')
    check('A','expected_document_count',m.get('expected_document_count')==30,'corpus_manifest.json')
    try:check('A','corpus_digest',digest(docs)==m.get('corpus_digest'),'corpus_manifest.json')
    except (KeyError,TypeError):fail('A','corpus_digest_uncomputable','corpus_manifest.json')
    ml=m.get('missing_files',[])
    check('A','missing_list_consistency',isinstance(ml,list) and all(isinstance(x,str) for x in ml) and set(ml)=={rel for rel in EXPECTED.values() if not (corpus/rel).is_file()},'corpus_manifest.json')
    bm={};pdf_cells={};N='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    def native_text(el):
        return ''.join((x.text or '') if x.tag==N+'t' else '\n' if x.tag in [N+'br',N+'cr'] else '\t' if x.tag==N+'tab' else '' for x in el.iter())
    for i,b in enumerate(blocks):
        if contract(b,BLOCK):continue
        bid=b['block_id'];did=b['doc_id'];loc=b['locator']
        if bid in bm:fail('A','duplicate_block_id',bid)
        bm[bid]=b
        check('A','block_id_document',bid.startswith(did+'-B'),bid)
        check('A','block_document_hash',did in dm and dm[did]['sha256']==b['source_sha256'],bid)
        check('A','block_LF_text','\r' not in b['text'],bid)
        check('A','block_locator_format',did in dm and loc['format']==dm[did]['format'],bid)
        try:
            if loc['format']=='docx':
                cells=[loc[k] for k in ['table_row','table_cell','paragraph_in_cell']]
                check('A','docx_locator_null_triplet',all(x is None for x in cells) or all(x is not None for x in cells),bid)
                if did not in native_docx:continue
                el=native_docx[did][loc['body_index']-1]
                if all(x is None for x in cells):
                    check('A','docx_paragraph_position',el.tag==N+'p' and b['kind'] in ['paragraph','heading'],bid)
                elif all(x is not None for x in cells):
                    check('A','docx_table_kind',el.tag==N+'tbl' and b['kind']=='table_cell',bid)
                    tr=el.findall(N+'tr')[loc['table_row']-1];tc=tr.findall(N+'tc')[loc['table_cell']-1]
                    complex_cell=tc.find(N+'tcPr/'+N+'vMerge') is not None or tc.find(N+'tcPr/'+N+'gridSpan') is not None or tc.find('.//'+N+'tbl') is not None
                    if complex_cell and b['extraction_verified']:fail('A','complex_cell_marked_verified',bid)
                    el=tc.findall(N+'p')[loc['paragraph_in_cell']-1]
                text=native_text(el)
                check('A','docx_native_text',text==b['text'] or any(r['before']==text and r['after']==b['text'] for r in b['reconstruction_notes']),bid)
            else:
                if did not in native_pdf:continue
                p=native_pdf[did];pn=loc['page']
                if pn>len(p.pages):fail('A','pdf_page_range',bid);continue
                pg=p.pages[pn-1];x0,y0,x1,y1=loc['bbox']
                inside=0<=x0<x1<=pg.width+.01 and 0<=y0<y1<=pg.height+.01
                check('A','pdf_bbox_native_page',inside,bid)
                if not inside:continue
                if b['kind']=='table_cell':
                    key=(did,pn)
                    if key not in pdf_cells:pdf_cells[key]=[box for t in pg.find_tables() for row in t.rows for box in row.cells if box]
                    check('A','pdf_native_table_cell',any(all(abs(a-z)<.1 for a,z in zip(box,loc['bbox'])) for box in pdf_cells[key]),bid)
                norm=lambda s:''.join((s or '').split())
                text=pg.crop(tuple(loc['bbox'])).extract_text(x_tolerance=2,y_tolerance=3) or ''
                check('A','pdf_bbox_text',norm(text)==norm(b['text']) or any(norm(r['before'])==norm(text) and r['after']==b['text'] for r in b['reconstruction_notes']),bid)
        except (IndexError,KeyError,TypeError,ValueError):fail('A','invalid_native_location',bid)
    for p in pdf_handles:p.close()
    for did,d in dm.items():
        for ve in d['version_evidence']:
            b=bm.get(ve['block_id'])
            check('A','version_evidence_binding',b is not None and b['doc_id']==did and ve['quote'] in b['text'],did)
        joined='\n'.join(x['quote'] for x in d['version_evidence'])
        for key in ['declared_business_branch','declared_business_commit']:
            if d[key] is not None:check('A','declared_version_exact_source',d[key] in joined,did+':'+key)
        if d['declared_document_date'] is not None:
            y,mo,da=d['declared_document_date'].split('-')
            check('A','declared_date_source',d['declared_document_date'] in joined or re.search(fr'{y}\s*年\s*{int(mo)}\s*月\s*{int(da)}\s*日',joined) is not None,did)
    for field,code in [('case_id','duplicate_case_id'),('family_id','duplicate_or_cross_split_family'),('question','duplicate_question')]:
        count=Counter(c.get(field) for c in cases if isinstance(c.get(field),str))
        for c in cases:
            if isinstance(c.get(field),str) and count.get(c[field],0)>1:fail('A',code,c.get('case_id','unknown'),c.get('case_id') if isinstance(c.get('case_id'),str) else None)
    validcases=[]
    for c in cases:
        cid=c.get('case_id','unknown')
        if contract(c,case_schema()):continue
        validcases.append(c);ev={};ptids=set();used=set()
        if not re.search(r'[\u3400-\u9fff]',c['question']):fail('A','question_requires_chinese',cid,cid)
        for e in c['evidence']:
            gid=e['evidence_id'];b=bm.get(e['block_id']);d=dm.get(e['doc_id'])
            if gid in ev:fail('A','duplicate_evidence_id',cid,cid)
            ev[gid]=e
            if b is None or d is None:fail('A','dangling_evidence_source',cid+':'+gid,cid);continue
            if not (e['doc_id']==b['doc_id'] and e['source_sha256']==b['source_sha256']==d['sha256']):fail('A','evidence_hash_identity',cid+':'+gid,cid)
            if not b['extraction_verified']:fail('A','unverified_evidence_block',cid+':'+gid,cid)
            s,t=e['char_start'],e['char_end']
            if not (0<=s<t<=len(b['text']) and b['text'][s:t]==e['quote']):fail('A','evidence_quote_slice',cid+':'+gid,cid)
        for pt in c['required_points']:
            if pt['point_id'] in ptids:fail('A','duplicate_point_id',cid,cid)
            ptids.add(pt['point_id'])
            for ss in pt['support_sets']:
                used.update(ss)
                if any(g not in ev or ev[g]['role']!='support' for g in ss):fail('A','dangling_or_wrong_support_ref',cid+':'+pt['point_id'],cid)
            for literal in pt['required_literals']:
                if literal not in pt['text'] or not any(literal in ev[g]['quote'] for ss in pt['support_sets'] for g in ss if g in ev):fail('A','literal_not_bound_to_point_source',cid+':'+pt['point_id'],cid)
            if pt['text'] not in c['reference_answer']:fail('A','reference_point_text_missing',cid+':'+pt['point_id'],cid)
        if c['expected_status']=='answered' and set(ev)!=used:fail('A','unused_answer_evidence',cid,cid)
        for fc in c['forbidden_claims']:
            if any(g not in ev for g in fc['evidence_ids']):fail('A','dangling_forbidden_ref',cid,cid)
        if c['category']=='cross_document' and len({e['doc_id'] for e in c['evidence'] if e['role']=='support'})<2:fail('A','cross_document_source_count',cid,cid)
        if c['absence_check'] and any(d not in dm for d in c['absence_check']['checked_doc_ids']):fail('A','absence_unknown_document',cid,cid)
        if c['clarification']:
            refs=set()
            for it in c['clarification']['interpretations']:
                refs.update(it['evidence_ids'])
                if any(g not in ev or ev[g]['role']!='disambiguation' for g in it['evidence_ids']):fail('A','clarification_evidence_ref',cid,cid)
            if refs!=set(ev):fail('A','unused_disambiguation_evidence',cid,cid)
            its=c['clarification']['interpretations']
            if its[0]['condition']==its[1]['condition'] or its[0]['answer_difference']==its[1]['answer_difference']:fail('A','identical_clarification_branches',cid,cid)
        r=c['review']
        if r['human_status']!='pending' or r['approved_by'] is not None or r['approved_at'] is not None:fail('A','draft_not_pending',cid,cid)
    ids={c['case_id'] for c in cases if isinstance(c.get('case_id'),str)};issueids=set()
    for i in issues:
        if contract(i,ISSUE):continue
        if i['issue_id'] in issueids:fail('A','duplicate_issue_id',i['issue_id'])
        issueids.add(i['issue_id'])
        check('A','issue_source_ids',set(i['affected_doc_ids'])<=set(EXPECTED) and set(i['affected_case_ids'])<=ids,i['issue_id'])
        for sl in i['source_locations']:
            if sl['doc_id'] not in EXPECTED:fail('A','issue_location_doc',i['issue_id'])
            if sl['locator'] is not None and sl['doc_id'] in dm:
                check('A','issue_location_format',sl['locator']['format']==dm[sl['doc_id']]['format'],i['issue_id'])
                if sl['locator']['format']=='pdf':check('A','issue_location_page',isinstance(dm[sl['doc_id']]['page_count'],int) and sl['locator']['page']<=dm[sl['doc_id']]['page_count'],i['issue_id'])
    if len(validcases)==len(cases):
        check('A','split_seed_and_quotas',sm.get('seed')==SEED and sm.get('dev_quota')==DEV,'split_manifest.json')
        alloc=allocation(cases)
        check('A','reproducible_allocation',sm.get('allocations')==alloc,'split_manifest.json')
        byfam={a['family_id']:a['split'] for a in alloc}
        for c in cases:
            if c['split']!=byfam.get(c['family_id']):fail('A','split_reproduction_mismatch',c['case_id'],c['case_id'])
        fams=sm.get('families',[])
        if not isinstance(fams,list):fail('A','family_manifest_type','split_manifest.json');fams=[]
        if any(not isinstance(f,dict) for f in fams):fail('A','family_manifest_member_type','split_manifest.json');fams=[]
        check('A','family_manifest_complete',len(fams)==len(cases) and {(f.get('family_id'),f.get('case_id')) for f in fams}=={(c['family_id'],c['case_id']) for c in cases},'split_manifest.json')
        for f in fams:
            for e in contract(f,obj({'family_id':st(),'case_id':st(),'main_intent':st(),'grouping_reason':st()})):fail('A','family_contract',e)
    answered=[c for c in validcases if c['expected_status']=='answered']
    label=lambda c,k:c.get(k) if isinstance(c.get(k),str) else '[invalid]'
    counts=dict(total=len(cases),split=dict(Counter(label(c,'split') for c in cases)),category=dict(Counter(label(c,'category') for c in cases)),status=dict(Counter(label(c,'expected_status') for c in cases)),category_by_split={s:dict(Counter(label(c,'category') for c in rows)) for s,rows in casefiles.items()},status_by_split={s:dict(Counter(label(c,'expected_status') for c in rows)) for s,rows in casefiles.items()},answered=len(answered),answered_topic=dict(Counter(c['topic'] for c in answered)),positive_doc_ids=sorted({e['doc_id'] for c in answered for e in c['evidence']}),answered_with_literals=sum(any(p['required_literals'] for p in c['required_points']) for c in answered),source_blocks=len(blocks),documents=len(docs))
    counts['positive_document_count']=len(counts['positive_doc_ids']);counts['positive_pdf_ids']=sorted(set(counts['positive_doc_ids'])&{f'DOC-{n:02d}' for n in range(24,30)})
    quotas_before=len(errors)
    check('B','total_and_split_quotas',counts['total']==60 and counts['split']=={'dev':40,'test':20},'dataset')
    for key,target in TOTAL.items():
        selected=[c for c in validcases if (c['category'] if c['category']!='boundary' else 'boundary:'+c['expected_status'])==key]
        check('B','stratum_quota',len(selected)==target and sum(c['split']=='dev' for c in selected)==DEV[key] and sum(c['split']=='test' for c in selected)==target-DEV[key],key)
    check('B','answered_denominator',len(answered)==50,'dataset')
    check('B','topic_coverage',all(2<=counts['answered_topic'].get(t,0)<=14 for t in TOPICS),'dataset')
    check('B','positive_document_coverage',counts['positive_document_count']>=20,'dataset')
    check('B','all_six_pdf_necessary_source_count',len(counts['positive_pdf_ids'])==6,'dataset')
    check('B','literal_case_coverage',counts['answered_with_literals']>=12,'dataset')
    quota_fail=any(e['group']=='B' for e in errors[quotas_before:])
    blocking=[i for i in issues if i.get('blocking')]
    missing_native=any(e['code'] in ['source_file_missing','source_file_unreadable','source_native_parse_unavailable'] for e in errors)
    scope=(set(dm)==set(EXPECTED) and len(docs)==30 and not m.get('missing_files') and not m.get('unreadable_files') and not blocking and not missing_native and audit.get('reading_complete') is True and not audit.get('unread_parts'))
    check('B','corpus_scope_and_reading_complete',scope,'corpus')
    # Pending human review is expected and never a structural failure.
    global_a=any(e['group']=='A' and 'case_id' not in e for e in errors)
    if mark:
        for c in validcases:c['review']['machine_checked']=not global_a and c['case_id'] not in bad_case
        for s,rows in casefiles.items():(dataset/(s+'.jsonl')).write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in rows),encoding='utf-8')
    a_ok=not any(e['group']=='A' for e in errors);b_ok=not any(e['group']=='B' for e in errors)
    status='draft' if a_ok and b_ok else 'incomplete'
    for group,description in [
      ('A','UTF-8/no BOM/duplicate keys; closed field contracts; corpus bytes/hash/digest/version; native DOCX/PDF positions and PDF cell boxes/text; exact evidence slices; case/family/question uniqueness; point/support/role/literal bindings; boundary structure; deterministic split; pending human status'),
      ('B','Fixed 30-document scope and recorded reading; 60/40/20 and category/substatus quotas; answered topics; >=20 documents; all six PDFs; >=12 literal cases')]:checks.append(dict(group=group,description=description,passed=not any(e['group']==group for e in errors)))
    report=dict(schema_version='1.0',dataset_version='debug-business-v1',checked_at=datetime.now().astimezone().isoformat(),mode='draft_only',structural_validation_passed=a_ok,target_quotas_met=not quota_fail,corpus_scope_complete=bool(scope),human_review_complete=False,ready_for_final_evaluation=False,dataset_status=status,actual_counts=counts,all_records_machine_checked=all(c.get('review',{}).get('machine_checked') is True for c in cases) and bool(cases),blocking_issues=blocking,errors=errors,checks_run=checks,semantic_checks_pending=['题目/答案正确性及原子要点充分性','support_sets 替代来源完整性与跨文档必要性','近重复与问题族边界','critical 与 forbidden_claims 合理性','clarify 是否只缺一个必要条件且必须追问','PDF 原页细节、表格列与图示关系逐题人工确认'],limitations=['只实现本数据契约关键词，未宣称通用 JSON Schema 解释器。','字符/哈希一致不证明答案语义正确；没有人工审批或系统答题。'])
    code=1 if not a_ok else 2 if not b_ok else 0;report['exit_code']=code
    if write:
        m['dataset_status']=status
        (dataset/'corpus_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (dataset/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return code,report

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--dataset-dir',type=Path,required=True);ap.add_argument('--corpus-root',type=Path,required=True);ap.add_argument('--mark-machine-checked',action='store_true');ap.add_argument('--write-schema',action='store_true');a=ap.parse_args()
    if a.write_schema:
        (a.dataset_dir/'dataset.schema.json').write_text(json.dumps(case_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return 0
    code,r=run(a.dataset_dir,a.corpus_root,a.mark_machine_checked)
    print(json.dumps({k:r[k] for k in ['structural_validation_passed','target_quotas_met','corpus_scope_complete','human_review_complete','ready_for_final_evaluation','dataset_status','exit_code']},ensure_ascii=False))
    return code

if __name__=='__main__':sys.exit(main())
