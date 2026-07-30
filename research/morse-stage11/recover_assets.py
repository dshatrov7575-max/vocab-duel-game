#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
import requests

ASSETS = [
    {"asset_id":"TRM1_BUTTON_MODE","url":"https://docs.owen.ru/book_img/2325/81067.png","expected_format":"PNG"},
    {"asset_id":"TRM1_BUTTON_LEFT","url":"https://docs.owen.ru/book_img/2325/81065.png","expected_format":"PNG"},
    {"asset_id":"TRM1_BUTTON_RIGHT","url":"https://docs.owen.ru/book_img/2325/81066.png","expected_format":"PNG"},
    {"asset_id":"TRM1_BUTTON_CONFIRM","url":"https://docs.owen.ru/book_img/2325/81064.png","expected_format":"PNG"},
    {"asset_id":"TRM1_DIN_INSTALL","url":"https://docs.owen.ru/book_img/2325/103396.png","expected_format":"PNG"},
    {"asset_id":"TRM1_DIN_DIMENSIONS","url":"https://docs.owen.ru/book_img/2325/103397.png","expected_format":"PNG"},
    {"asset_id":"2TRM1_FORMULA_1","url":"https://docs.owen.ru/book_img/2329/81013.svg","expected_format":"SVG"},
    {"asset_id":"2TRM1_FORMULA_2","url":"https://docs.owen.ru/book_img/2329/81012.svg","expected_format":"SVG"}
]

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main() -> int:
    out=Path(sys.argv[1] if len(sys.argv)>1 else 'recovered-assets')
    out.mkdir(parents=True, exist_ok=True)
    sess=requests.Session()
    headers={"User-Agent":"Mozilla/5.0 MORSE-research-asset-recovery/0.1","Accept":"image/png,image/svg+xml,*/*;q=0.8","Referer":"https://docs.owen.ru/"}
    receipts=[]
    for item in ASSETS:
        rec=dict(item)
        ext='.png' if item['expected_format']=='PNG' else '.svg'
        path=out/(item['asset_id']+ext)
        try:
            r=sess.get(item['url'],headers=headers,timeout=(30,120),allow_redirects=True)
            r.raise_for_status()
            data=r.content
            if item['expected_format']=='PNG' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise RuntimeError('PNG_MAGIC_MISMATCH')
            if item['expected_format']=='SVG' and b'<svg' not in data[:4096].lower():
                raise RuntimeError('SVG_MARKUP_MISSING')
            path.write_bytes(data)
            rec.update({"status":"SUCCESS","final_url":r.url,"content_type":r.headers.get('content-type'),"bytes":len(data),"sha256":sha256(data),"file":path.name})
        except Exception as e:
            rec.update({"status":"FAILED","error":f"{type(e).__name__}: {e}"})
        receipts.append(rec)
    root={
        "work_id":"MORSE-STAGE11-SOURCE-ASSET-RECOVERY-20260730-01",
        "asset_count":len(receipts),
        "success_count":sum(r['status']=='SUCCESS' for r in receipts),
        "failure_count":sum(r['status']!='SUCCESS' for r in receipts),
        "case_selection_allowed":False,
        "corpus_patch_allowed":False,
        "semantic_rules_changed":False,
        "automatic_merge":False,
        "merge_performed":False,
        "assets":receipts
    }
    (out/'ROOT_RECEIPT.json').write_text(json.dumps(root,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SUMMARY.txt').write_text('\n'.join([
        f"ASSETS={root['asset_count']}",f"SUCCESS={root['success_count']}",f"FAILED={root['failure_count']}",
        "CASE_SELECTION_ALLOWED=false","CORPUS_PATCH_ALLOWED=false","AUTOMATIC_MERGE=false"
    ])+'\n',encoding='utf-8')
    return 0 if root['failure_count']==0 else 2

if __name__=='__main__':
    raise SystemExit(main())
