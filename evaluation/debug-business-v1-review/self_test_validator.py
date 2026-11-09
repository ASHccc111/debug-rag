"""Mutation tests against temporary dataset copies; never invokes a RAG system."""
import argparse
import importlib.util
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dataset-dir',required=True,type=Path);ap.add_argument('--corpus-root',required=True,type=Path);ap.add_argument('--work-root',type=Path,default=Path('tmp/eval-validator-selftest'));a=ap.parse_args()
    root=a.work_root.resolve();root.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('draft_validator',a.dataset_dir/'validate_dataset.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    readl=lambda p:[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()]
    def put(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def putl(p,x):p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in x),encoding='utf-8')
    results=[]
    def exercise(name,mutate,expected_code,required_code):
        with tempfile.TemporaryDirectory(prefix='mutation-',dir=root) as td:
            target=Path(td).resolve()
            # Verify the cleanup target before the TemporaryDirectory context deletes it.
            assert target.parent==root and target.is_relative_to(root)
            for f in a.dataset_dir.iterdir():
                if f.is_file():shutil.copyfile(f,target/f.name)
            mutate(target)
            code,report=v.run(target,a.corpus_root,False,False)
            codes=sorted({x['code'] for x in report['errors']})
            detected=code==expected_code and (required_code is None or required_code in codes)
            results.append(dict(name=name,expected_exit_code=expected_code,actual_exit_code=code,expected_error_code=required_code,detected_error_codes=codes,passed=detected))
    def editdev(fn):
        def go(p):
            f=p/'dev.jsonl';rows=readl(f);fn(rows);putl(f,rows)
        return go
    exercise('valid_unmodified_baseline',lambda p:None,0,None)
    exercise('duplicate_case_id',editdev(lambda r:r[1].update(case_id=r[0]['case_id'])),1,'duplicate_case_id')
    def across(p):
        rows=readl(p/'dev.jsonl');other=readl(p/'test.jsonl');rows[0]['family_id']=other[0]['family_id'];putl(p/'dev.jsonl',rows)
    exercise('family_id_across_splits',across,1,'duplicate_or_cross_split_family')
    exercise('wrong_quote',editdev(lambda r:r[0]['evidence'][0].update(quote=r[0]['evidence'][0]['quote']+'错')),1,'evidence_quote_slice')
    def fake_sha(p):
        m=read(p/'corpus_manifest.json');m['documents'][0]['sha256']='0'*64;m['corpus_digest']=v.digest(m['documents']);put(p/'corpus_manifest.json',m)
    exercise('forged_physical_file_sha256',fake_sha,1,'file_sha256')
    exercise('dangling_G_reference',editdev(lambda r:r[0]['required_points'][0].update(support_sets=[['G999']])),1,'dangling_or_wrong_support_ref')
    def wrongquota(p):
        sm=read(p/'split_manifest.json');victim=max((x for x in sm['allocations'] if x['stratum']=='fact'),key=lambda x:x['rank']);f=p/(victim['split']+'.jsonl');rows=readl(f);rows=[c for c in rows if c['family_id']!=victim['family_id']];putl(f,rows)
        sm['families']=[x for x in sm['families'] if x['family_id']!=victim['family_id']];sm['allocations']=[x for x in sm['allocations'] if x['family_id']!=victim['family_id']];put(p/'split_manifest.json',sm)
    exercise('wrong_category_quota_valid_structure',wrongquota,2,'stratum_quota')
    def duplicatekey(p):
        f=p/'dev.jsonl';lines=f.read_text(encoding='utf-8').splitlines();lines[0]='{"split":"dev",'+lines[0][1:];f.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    exercise('duplicate_JSON_key',duplicatekey,1,'jsonl_encoding_or_object')
    def bom(p):
        f=p/'test.jsonl';f.write_bytes(b'\xef\xbb\xbf'+f.read_bytes())
    exercise('UTF8_BOM_rejected',bom,1,'file_encoding_or_json')
    exercise('extra_nested_field',editdev(lambda r:r[0]['required_points'][0].update(extra=True)),1,'case_contract')
    exercise('bool_is_not_integer',editdev(lambda r:r[0]['evidence'][0].update(char_start=True)),1,'case_contract')
    exercise('invalid_family_field_type',editdev(lambda r:r[0].update(family_id=[])),1,'case_contract')
    exercise('invalid_case_id_type',editdev(lambda r:r[0].update(case_id=[])),1,'case_contract')
    def badpdf(p):
        f=p/'source_blocks.jsonl';rows=readl(f);next(b for b in rows if b['doc_id']=='DOC-24')['locator']['page']=999;putl(f,rows)
    exercise('PDF_page_out_of_bounds',badpdf,1,'pdf_page_range')
    def unverified(p):
        c=readl(p/'dev.jsonl')[0];f=p/'source_blocks.jsonl';rows=readl(f);next(b for b in rows if b['block_id']==c['evidence'][0]['block_id'])['extraction_verified']=False;putl(f,rows)
    exercise('unverified_block_used_as_evidence',unverified,1,'unverified_evidence_block')
    exercise('human_approval_cannot_be_agent_signed',editdev(lambda r:r[0]['review'].update(human_status='approved',approved_by='mutation-only',approved_at='2026-11-05T10:00:00+08:00')),1,'draft_not_pending')
    report=dict(executed_at=datetime.now().astimezone().isoformat(),mode='temporary_copy_mutation',source_dataset_unchanged=True,contains_test_questions_or_answers=False,total_checks=len(results),passed_checks=sum(r['passed'] for r in results),all_passed=all(r['passed'] for r in results),results=results,notes=['退出码2用例保留合法结构，仅减少一个 fact/test 代表题并同步问题族清单，单独检验 B 组。','临时副本复用只读的真实语料；未改原始 DOCX/PDF。','这里只证明列出的损坏能被检出，不证明校验器没有其他缺陷。'])
    put(a.dataset_dir/'validator_self_test.json',report)
    print(json.dumps({k:report[k] for k in ['total_checks','passed_checks','all_passed']},ensure_ascii=False))
    return 0 if report['all_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
