import json,re,hashlib,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import pdfplumber
from docx import Document

WS=Path('D:/code/debug-rag'); CORPUS=WS/'note'; WORK=Path(__file__).parent
SPEC=Path('C:/Users/admin/Downloads/9e20f478899dc29eb19741386f9343c8_6982788308564579168_m.md')
EXPECTED=re.findall(r'^(?:docx|pdf)/\d{2}_.+\.(?:docx|pdf)$',SPEC.read_text(encoding='utf-8'),re.M)
assert len(EXPECTED)==30
now=datetime.now(ZoneInfo('Asia/Shanghai'))
OUT=WS/'evaluation/debug-business-v1'
if '--resume' in sys.argv:
    OUT=Path(json.loads((WORK/'paths.json').read_text(encoding='utf-8'))['output'])
else:
    if OUT.exists() and any(OUT.iterdir()): OUT=OUT.with_name('debug-business-v1-draft-'+now.strftime('%Y%m%d-%H%M%S'))
OUT.mkdir(parents=True,exist_ok=True)
(WORK/'paths.json').write_text(json.dumps({'output':str(OUT),'corpus':str(CORPUS)},ensure_ascii=False),encoding='utf-8')
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};W='{'+NS['w']+'}'
blocks=[]; documents=[]; issues=[]; readview=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def issue(doc,kind,details,loc=None,blocking=False):
    issues.append({'issue_id':f'ISSUE-{len(issues)+1:04d}','issue_type':kind,'affected_doc_ids':[doc],'affected_case_ids':[],'details':details,'source_locations':[{'doc_id':doc,'locator':loc}],'blocking':blocking,'required_resolution':'人工复核所述位置与语义；不得把程序提取核对当作人工审批。'})
def push(doc,digest,kind,path,loc,text,verified=True):
    text=text.replace('\r\n','\n').replace('\r','\n')
    if not text.strip():return
    k=sum(b['doc_id']==doc for b in blocks)+1
    row={'block_id':f'{doc}-B{k:06d}','doc_id':doc,'source_sha256':digest,'kind':kind,'section_path':list(path),'locator':loc,'text':text,'extraction_verified':verified,'reconstruction_notes':[]}
    blocks.append(row);readview.append(f"{row['block_id']} {text}")
def txtp(el):
    out=[]
    for x in el.iter():
        if x.tag==W+'t':out.append(x.text or '')
        elif x.tag in [W+'br',W+'cr']:out.append('\n')
        elif x.tag==W+'tab':out.append('\t')
    return ''.join(out)
for rel in EXPECTED:
    doc='DOC-'+Path(rel).name[:2];path=CORPUS/rel
    if not path.exists():issue(doc,'missing_file',rel,blocking=True);continue
    raw=path.read_bytes();digest=sha(raw);fmt=path.suffix[1:]
    row={'doc_id':doc,'file':rel,'title':None,'format':fmt,'sha256':digest,'byte_size':len(raw),'page_count':None,'declared_business_branch':None,'declared_business_commit':None,'declared_document_date':None,'version_evidence':[],'source_code_crosscheck':'not_available','extraction_issues':[]}
    start=len(blocks);readview.append('\n### '+doc+' '+rel)
    section=[]
    try:
        if fmt=='docx':
            with ZipFile(path) as z:root=ET.fromstring(z.read('word/document.xml'))
            body=root.find('w:body',NS);tail=False
            for bi,el in enumerate(body,1):
                tag=el.tag.rsplit('}',1)[-1]
                if tag=='p':
                    text=txtp(el);style=el.find('w:pPr/w:pStyle',NS)
                    sty=style.get(W+'val','') if style is not None else ''
                    if text=='源码依据与版本回查':tail=True
                    if tail:continue
                    kind='heading' if sty in ['Title','Heading1','Heading2'] else 'paragraph'
                    if sty=='Title':row['title']=text;section=[text]
                    elif kind=='heading':section=[row['title'],text]
                    push(doc,digest,kind,section,{'format':'docx','body_index':bi,'table_row':None,'table_cell':None,'paragraph_in_cell':None},text)
                elif tag=='tbl' and not tail:
                    for ri,tr in enumerate(el.findall('w:tr',NS),1):
                        for ci,tc in enumerate(tr.findall('w:tc',NS),1):
                            safe=not any(tc.findall('.//w:tbl',NS)) and tc.find('w:tcPr/w:vMerge',NS) is None and tc.find('w:tcPr/w:gridSpan',NS) is None
                            for pi,pe in enumerate(tc.findall('w:p',NS),1):
                                loc={'format':'docx','body_index':bi,'table_row':ri,'table_cell':ci,'paragraph_in_cell':pi}
                                push(doc,digest,'table_cell',section,loc,txtp(pe),safe)
                                if not safe:issue(doc,'complex_table','嵌套或合并表格位置不能可靠表达',loc,True)
        else:
            with pdfplumber.open(path) as pdf:
                row['page_count']=len(pdf.pages);tail=False
                for page in pdf.pages:
                    # pdfplumber coordinates are top-origin points after its rotation handling.
                    tables=page.find_tables(table_settings={'vertical_strategy':'lines','horizontal_strategy':'lines'})
                    tableboxes=[t.bbox for t in tables]
                    for tab in tables:
                        content=tab.extract(x_tolerance=2,y_tolerance=3)
                        for ri,tr in enumerate(tab.rows):
                            for ci,box in enumerate(tr.cells):
                                if box is None:continue
                                text=(content[ri][ci] or '')
                                push(doc,digest,'table_cell',section,{'format':'pdf','page':page.page_number,'bbox':list(box)},text)
                    chars=[c for c in page.chars if c.get('text') and c['top']>30 and c['bottom']<page.height-35 and not any(b[0]-.2<=c['x0']<=b[2]+.2 and b[1]-.2<=c['top']<=b[3]+.2 for b in tableboxes)]
                    groups=[]
                    for c in sorted(chars,key=lambda c:(round(c['top'],1),c['x0'])):
                        if groups and abs(groups[-1][0]['top']-c['top'])<2:groups[-1].append(c)
                        else:groups.append([c])
                    # Non-table prose is retained line-wise to avoid inventing paragraph joins.
                    for line in groups:
                        line=sorted(line,key=lambda c:c['x0']);text=''.join(c['text'] for c in line)
                        if text=='源码依据与版本回查':tail=True
                        is_version=text.startswith('统一基线提交 ')
                        if tail and not is_version:continue
                        size=max(c.get('size',0) for c in line)
                        kind='heading' if size>=12.5 else 'paragraph'
                        if row['title'] is None:row['title']=text;section=[text]
                        elif kind=='heading':section=[row['title'],text]
                        loc={'format':'pdf','page':page.page_number,'bbox':[min(c['x0'] for c in line),min(c['top'] for c in line),max(c['x1'] for c in line),max(c['bottom'] for c in line)]}
                        # Diagram node labels remain text only; no inferred edges are stored.
                        if page.page_number>1 and loc['bbox'][0]>70 and size<12 and not is_version:kind='diagram_text'
                        push(doc,digest,kind,section,loc,text)
                    if page.page_number==1:
                        footer=[c for c in page.chars if c['top']>=page.height-35 and c['x0']<400]
                        if footer:
                            ft=''.join(c['text'] for c in sorted(footer,key=lambda c:c['x0']))
                            if '2026' in ft:
                                push(doc,digest,'paragraph',[row['title'],'资料日期声明'],{'format':'pdf','page':1,'bbox':[min(c['x0'] for c in footer),min(c['top'] for c in footer),max(c['x1'] for c in footer),max(c['bottom'] for c in footer)]},ft)
            own=blocks[start:]
            own.sort(key=lambda b:(b['locator']['page'],b['locator']['bbox'][1],b['locator']['bbox'][0]))
            section=[]
            for i,b in enumerate(own,1):
                b['block_id']=f'{doc}-B{i:06d}'
                if b['kind']=='heading':section=[row['title']] if b['text']==row['title'] else [row['title'],b['text']]
                b['section_path']=section.copy()
            blocks[start:]=own
            issue(doc,'pdf_review','表格单元格保留原始断行；图示只提取节点文字，箭头关系须结合页面与正文人工复核。已提取全部页面的正文和表格，源码依据尾部不作为答案依据。')
    except Exception as e:
        row['extraction_issues'].append({'code':'extraction_failed','exception_type':type(e).__name__});issue(doc,'extraction_failed',type(e).__name__,blocking=True)
    own=blocks[start:]
    for b in own:
        t=b['text']
        branch=re.search(r'p/caijiamin/feat_debug_2th',t);commit=re.search(r'\b[0-9a-f]{40}\b',t);date=re.search(r'2026\s*年\s*11\s*月\s*3\s*日',t)
        if branch:row['declared_business_branch']=branch[0]
        if commit:row['declared_business_commit']=commit[0]
        if date:row['declared_document_date']='2026-11-03'
        if branch or commit or date:row['version_evidence'].append({'block_id':b['block_id'],'quote':t})
    documents.append(row)
manifest={'schema_version':'1.0','dataset_version':'debug-business-v1','dataset_status':'incomplete','created_at':now.isoformat(),'expected_document_count':30,'actual_document_count':len(documents),'missing_files':[f for f in EXPECTED if not (CORPUS/f).exists()],'unreadable_files':[],'corpus_digest':sha(json.dumps([{'doc_id':d['doc_id'],'sha256':d['sha256']} for d in sorted(documents,key=lambda x:x['doc_id'])],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()),'documents':documents,'extraction_environment':{'docx':'stdlib XML direct body order','pdf':f'pdfplumber {pdfplumber.__version__}','pdf_coordinate_convention':'pdfplumber x0/top/x1/bottom in points; page rotation handled by pdfplumber/pdfminer; page bbox uses reported mediabox; no crop transform; pages examined have rotation 0 and cropbox equal mediabox','source_code_note':'当前工作区没有与声明提交对应的公司源码，未使用工作区外源码作为核对依据。'}}
for name,data in [('corpus_manifest.json',manifest)]: (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for name,rows in [('source_blocks.jsonl',blocks),('review_queue.jsonl',issues)]: (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
(WORK/'readview.txt').write_text('\n'.join(readview),encoding='utf-8')
(WORK/'body_reading.txt').write_text('\n'.join(b['block_id']+' '+b['text'] for b in blocks if b['kind']!='table_cell' or b['doc_id']>='DOC-24'),encoding='utf-8')
(WORK/'run_environment.json').write_text(json.dumps({'input_absolute':str(CORPUS),'output_absolute':str(OUT),'python':sys.executable,'created_at':now.isoformat()},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'output':str(OUT),'documents':len(documents),'blocks':len(blocks),'issues':len(issues)},ensure_ascii=False))
