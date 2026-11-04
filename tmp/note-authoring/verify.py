import json, re, subprocess, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from docx import Document
from pypdf import PdfReader
from PIL import Image, ImageOps, ImageDraw, ImageFont

TMP=Path(__file__).parent; OUT=Path('D:/code/debug-rag/note')
POP=Path('C:/Users/admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin')
manifest=json.loads((TMP/'manifest.json').read_text(encoding='utf-8'))
checks=[];jobs=[]
for item in manifest:
    path=Path(item['path'])
    if item['format']=='docx':
        doc=Document(path)
        text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        pdf=TMP/'qa'/f"{item['number']:02d}_preview.pdf"
        native=False
    else:
        pdf=path;text='\n'.join(p.extract_text() or '' for p in PdfReader(pdf).pages);native=True
    assert len(text)>300,(path,'short document')
    assert '9010928' in text,(path,'baseline absent')
    assert not any(s in text for s in ['RAG_DEEPSEEK_API_KEY=','storePassword','keyPassword','Bearer ']),'sensitive config token'
    pages=len(PdfReader(pdf).pages)
    checks.append(dict(number=item['number'],file=path.name,pages=pages,characters=len(text),native_pdf=native))
    target=TMP/'render'/f"{item['number']:02d}";target.mkdir(parents=True,exist_ok=True)
    for stale in target.glob('page-*.png'):stale.unlink()
    jobs.append((pdf,target))

def render(job):
    pdf,target=job
    cmd=[str(POP/'pdftoppm.exe'),'-r','100','-png',str(pdf),str(target/'page')]
    done=subprocess.run(cmd,capture_output=True,text=True)
    if done.returncode:raise RuntimeError(done.stderr[:300])
    return len(list(target.glob('page-*.png')))

with ThreadPoolExecutor(max_workers=4) as pool:
    counts=list(pool.map(render,jobs))

imgs=[]
for entry in checks:
    folder=TMP/'render'/f"{entry['number']:02d}"
    pages=sorted(folder.glob('page-*.png'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
    assert len(pages)==entry['pages']
    imgs += [(f"{entry['number']:02d}  {p.stem}",p) for p in pages]
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',22)
for start in range(0,len(imgs),4):
    canvas=Image.new('RGB',(1660,2420),'#ccd3db');draw=ImageDraw.Draw(canvas)
    for i,(label,path) in enumerate(imgs[start:start+4]):
        im=Image.open(path).convert('RGB');im.thumbnail((800,1150))
        x=20+(i%2)*830;y=35+(i//2)*1210
        draw.text((x,y-29),label,font=font,fill='black');canvas.paste(im,(x,y))
    canvas.save(TMP/'qa'/f"sheet-{start//4:02d}.jpg",quality=90)
(TMP/'verification.json').write_text(json.dumps({'documents':checks,'pages':sum(x['pages'] for x in checks),'characters':sum(x['characters'] for x in checks),'native_docx_render':'unavailable: bundled LibreOffice absent; OOXML content preview used','images':len(imgs),'sheets':(len(imgs)+3)//4},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(checks),'docx':24,'pdf':6,'pages':sum(x['pages'] for x in checks),'characters':sum(x['characters'] for x in checks),'sheets':(len(imgs)+3)//4,'by_document':[[x['number'],x['pages']] for x in checks]},ensure_ascii=False))
