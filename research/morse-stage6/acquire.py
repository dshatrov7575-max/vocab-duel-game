#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

WORK_ID = "MORSE-STAGE6-EXACT-SOURCE-ACQUISITION-20260730-01"
MAX_BYTES = 180 * 1024 * 1024
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36"

SOURCES = [
    {"id":"NEW300-OWEN-TRM1-RU","publisher":"ОВЕН","title":"ТРМ1. Руководство по эксплуатации","edition":"1-RU-132358-1.11","landing":"https://docs.owen.ru/product/trm1","components":[("main","HTML","https://docs.owen.ru/product/trm1/doc/rukovodstvo-po-ekspluatacii-trm1",None)]},
    {"id":"NEW300-OWEN-2TRM1-RU","publisher":"ОВЕН","title":"2ТРМ1. Руководство по эксплуатации","edition":"1-RU-132548-1.11","landing":"https://docs.owen.ru/product/2trm1","components":[("main","HTML","https://docs.owen.ru/product/2trm1/doc/rukovodstvo-po-ekspluatacii-2trm1",None)]},
    {"id":"NEW300-TEPLOCOM-PREM-RU","publisher":"Теплоком","title":"ПРЭМ. Руководство по эксплуатации","edition":"ред.1.3, 2026","landing":"https://teplocom-sale.ru/support/rashodomery/","components":[("main","PDF","https://teplocom-sale.ru/upload/medialibrary/69f/d3jdk4ni8n3mi2tdbmlqc1wwf85kplf2/Rukovodstvo-po-ekspluatatsii-na-preobrazovateli-raskhoda-PREM-_red.1.3_-2026g..pdf",57)]},
    {"id":"NEW300-ELEMER-AIR10L-RU","publisher":"ЭЛЕМЕР","title":"АИР-10L. Руководство по эксплуатации","edition":"официальный re_air_10l.pdf","landing":"https://www.elemer.ru/catalog/datchiki-davleniya-i-manometry/datchiki-davleniya/air-10l/","components":[("main","PDF","https://www.elemer.ru/upload/iblock/c4e/l9x2lcabu82v0wasblvgpk3r645t5u1n/re_air_10l.pdf",None)]},
    {"id":"NEW300-ELEMER-IPM0399M0-RU","publisher":"ЭЛЕМЕР","title":"ИПМ 0399/М0. Руководство по эксплуатации","edition":"официальный re_ipm_0399_m0.pdf","landing":"https://www.elemer.ru/catalog/funktsionalnaya-apparatura/modulnye-preobrazovateli/ipm-0399-m0/","components":[("main","PDF","https://www.elemer.ru/upload/iblock/f3f/re_ipm_0399_m0.pdf",None)]},
    {"id":"NEW300-VZLJOT-TPS-RU","publisher":"Взлет","title":"ВЗЛЕТ ТПС. Руководство по эксплуатации","edition":"В65.00-00.00 РЭ; doc4.3","landing":"https://vzljot.ru/catalogue/uchet_teplovoy_energii/vzlet_tps/","components":[("main","PDF","https://vzljot.ru/upload/iblock/801/iomz3qehq3lmtlyhos6by8x2pw9m3xnh/re_tps_doc4.3.pdf",36)]},
    {"id":"NEW300-VZLJOT-AS-USB-RS-RU","publisher":"Взлет","title":"ВЗЛЕТ USB-RS-232/RS-485. Руководство","edition":"В56.00-00.00 РЭ; doc2.6","landing":"https://vzljot.ru/catalogue/adaptery-_registratory-_modemy/preobrazovatel_interfeysov/vzlet_as_mod-_2-0_usb-rs-232-rs-485/","components":[("main","PDF","https://vzljot.ru/upload/iblock/88b/zhw4nz6ee492ut1eeghdv73ah8kv1xri/re_ads_usb-rs_doc_2_6.pdf",14)]},
    {"id":"NEW300-TERMOTRONIC-T1-RU","publisher":"Термотроник","title":"Питерфлоу Т1. Руководство","edition":"ред.1.08","landing":"https://termotronic.ru/download/","components":[("main","PDF","https://termotronic.ru/upload/files/re_t1_red_1.08.pdf",33)]},
    {"id":"NEW300-TERMOTRONIC-T3-RU","publisher":"Термотроник","title":"Питерфлоу Т3. Руководство","edition":"ред.1.09, 2025","landing":"https://termotronic.ru/download/","components":[("main","PDF","https://termotronic.ru/upload/files/re_t3-obshepromyshlennoe_red._1.09.pdf",57)]},
    {"id":"NEW300-EMIS-EV205-RU","publisher":"ЭМИС","title":"ЭМИС-ВИХРЬ 205. Руководство","edition":"V1.1.8, 25.05.2026","landing":"https://emis-kip.ru/prod/emis_vihr_205/","components":[("main","PDF","https://emis-kip.ru/documents/eks-doc/vikhr/%D0%AD%D0%92205%20%D0%A0%D0%AD%20%D1%87%D0%B0%D1%81%D1%82%D1%8C%203.pdf",56)]},
    {"id":"NEW300-OWEN-TRM500-RU","publisher":"ОВЕН","title":"ТРМ500. Руководство","edition":"1-RU-20198-1.19","landing":"https://docs.owen.ru/product/trm500","components":[("main","HTML","https://docs.owen.ru/product/trm500/doc/rukovodstvo-po-ekspluatacii-trm500",None)]},
    {"id":"NEW300-TEPLOCOM-VKT9-RU","publisher":"Теплоком","title":"ВКТ-9. Руководство","edition":"v01.06, 2025","landing":"https://teplocom-sale.ru/product/vychislitel-kolichestva-teploty-vkt-9-02/","components":[("main","PDF","https://teplocom-sale.ru/upload/medialibrary/900/c7mqnveonlvnh9shoytb09cgi5npqemu/Rukovodstvo_po_ekspluatatsii_VKT_9_2025_red._v01.06_new.pdf",None)]},
    {"id":"NEW300-VZLJOT-TER-RU","publisher":"Взлет","title":"ВЗЛЕТ ТЭР. Руководство","edition":"части I doc3.5 + II doc2.8","landing":"https://vzljot.ru/catalogue/izmerenie_raskhoda_zhidkostey/elektromagnitnyy_metod_izmereniy/vzlet_ter_aes/","components":[("part1","PDF","https://vzljot.ru/upload/iblock/f02/4os6ajnqi6kvhn6qs21pz3535yki6l8y/re1_ter.xxx_doc3.5.pdf",50),("part2","PDF","https://vzljot.ru/upload/iblock/8ea/4v0hzo4clur50fhfzasvry3u6bf9k85q/re2_ter.x%D1%85%D1%85_doc2.8.pdf",38)]},
    {"id":"NEW300-TERMOTRONIC-TV7M-RU","publisher":"Термотроник","title":"ТВ7 исполнения М. Руководство","edition":"ред.1.09","landing":"https://termotronic.ru/download/","components":[("main","PDF","https://termotronic.ru/upload/files/tv7-ispolnenie_m_re_red.1.09.pdf",59)]},
    {"id":"NEW300-EMIS-IM2300-RU","publisher":"ЭМИС","title":"ИМ 2300. Руководство","edition":"ИМ23.00.001РЭ; 2017","landing":"https://emis-kip.ru/prod/im2300/","components":[("main","PDF","https://emis-kip.ru/documents/eks-doc/im2300/IM2300Re.pdf",54)]},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()


def canon(text: str) -> str:
    text=unicodedata.normalize("NFC",text).replace("\r\n","\n").replace("\r","\n")
    text=re.sub(r"[ \t]+"," ",text)
    text=re.sub(r" *\n *","\n",text)
    return re.sub(r"\n{3,}","\n\n",text).strip()+"\n"


def session() -> requests.Session:
    retry=Retry(total=4,connect=4,read=4,status=4,backoff_factor=1.5,status_forcelist=(408,429,500,502,503,504),allowed_methods=frozenset({"GET"}))
    s=requests.Session(); s.mount("https://",HTTPAdapter(max_retries=retry)); return s


def download(s: requests.Session,url: str,landing: str,target: Path) -> dict[str,Any]:
    headers={"User-Agent":UA,"Accept":"application/pdf,text/html,*/*;q=0.8","Accept-Language":"ru-RU,ru;q=0.9","Referer":landing}
    started=time.monotonic()
    with s.get(url,headers=headers,stream=True,timeout=(30,180),allow_redirects=True) as r:
        r.raise_for_status(); total=0
        with target.open("wb") as f:
            for chunk in r.iter_content(1<<20):
                if not chunk: continue
                total+=len(chunk)
                if total>MAX_BYTES: raise RuntimeError("MAX_BYTES_EXCEEDED")
                f.write(chunk)
        return {"status":r.status_code,"final_url":r.url,"headers":dict(r.headers),"seconds":round(time.monotonic()-started,3),"bytes":total}


def inspect_pdf(path: Path,snapshot: Path,expected: int|None) -> dict[str,Any]:
    if path.read_bytes()[:5]!=b"%PDF-": raise RuntimeError("PDF_MAGIC_MISMATCH")
    reader=PdfReader(str(path)); chunks=[]; page_chars=[]; errs=[]
    for i,p in enumerate(reader.pages,1):
        try: t=canon(p.extract_text() or "") if (p.extract_text() or "").strip() else ""
        except Exception as e: t=""; errs.append({"page":i,"error":str(e)})
        page_chars.append(len(t)); chunks.append(f"=== PAGE {i} / {len(reader.pages)} ===\n{t}")
    snapshot.write_text(canon("\n".join(chunks)),encoding="utf-8")
    return {"page_count":len(reader.pages),"expected_pages":expected,"page_count_match":expected is None or expected==len(reader.pages),"pages_with_text":sum(v>0 for v in page_chars),"text_chars":sum(page_chars),"text_status":"VERIFIED" if sum(page_chars)>200 else "WEAK_OR_SCANNED","snapshot_sha256":sha(snapshot),"extraction_errors":errs}


def inspect_html(path: Path,snapshot: Path) -> dict[str,Any]:
    raw=path.read_bytes(); text=raw.decode("utf-8",errors="replace"); soup=BeautifulSoup(text,"lxml")
    for tag in soup(["script","style","noscript","svg"]): tag.decompose()
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    body=canon(soup.get_text("\n",strip=True)); snapshot.write_text(canon(f"=== HTML ===\nTITLE: {title}\n\n{body}"),encoding="utf-8")
    return {"text_chars":len(body),"text_status":"VERIFIED" if len(body)>500 else "WEAK","snapshot_sha256":sha(snapshot)}


def main() -> int:
    out=Path(sys.argv[1] if len(sys.argv)>1 else "vault"); out.mkdir(parents=True,exist_ok=True); s=session(); receipts=[]; flat=[]
    for src in SOURCES:
        d=out/src["id"]; d.mkdir(exist_ok=True); sr={k:src[k] for k in ("id","publisher","title","edition","landing")}; sr["case_selection_allowed"]=False; sr["components"]=[]
        for cid,fmt,url,expected in src["components"]:
            ext=".pdf" if fmt=="PDF" else ".html"; target=d/(cid+ext); snap=d/(cid+".derived.txt")
            cr={"source_id":src["id"],"component_id":cid,"component_key":src["id"]+"::"+cid,"format":fmt,"official_url":url,"expected_pages":expected,"status":"FAILED","case_selection_allowed":False}
            try:
                cr["download"]=download(s,url,src["landing"],target); cr["local_path"]=str(target); cr["size_bytes"]=target.stat().st_size; cr["source_sha256"]=sha(target)
                cr.update(inspect_pdf(target,snap,expected) if fmt=="PDF" else inspect_html(target,snap)); cr["snapshot_path"]=str(snap); cr["status"]="SUCCESS"
            except Exception as e:
                cr["error"]=f"{type(e).__name__}: {e}"; cr["traceback_tail"]=traceback.format_exc()[-2500:]
            sr["components"].append(cr); flat.append(cr)
        ok=[x for x in sr["components"] if x["status"]=="SUCCESS"]; sr["status"]="SUCCESS" if len(ok)==len(sr["components"]) else ("PARTIAL" if ok else "FAILED")
        material="\n".join(f"{x['component_id']}:{x['source_sha256']}" for x in sorted(ok,key=lambda x:x["component_id"])); sr["component_set_sha256"]=hashlib.sha256(material.encode()).hexdigest() if material else None
        (d/"ACQUISITION_RECEIPT.json").write_text(json.dumps(sr,ensure_ascii=False,indent=2),encoding="utf-8"); receipts.append(sr)
    ok=[x for x in flat if x["status"]=="SUCCESS"]; bad=[x for x in flat if x["status"]!="SUCCESS"]
    def dup(field):
        g={}
        for x in ok:
            if x.get(field): g.setdefault(x[field],[]).append(x["component_key"])
        return [{"value":v,"components":k} for v,k in g.items() if len(k)>1]
    root={"work_id":WORK_ID,"generated_at_utc":now(),"status":"COMPLETE" if not bad else "PARTIAL_WITH_FAILURES","source_count":len(receipts),"source_success_count":sum(x["status"]=="SUCCESS" for x in receipts),"component_count":len(flat),"component_success_count":len(ok),"component_failure_count":len(bad),"original_byte_lock_count":len(ok),"derived_snapshot_lock_count":sum(bool(x.get("snapshot_sha256")) for x in ok),"exact_byte_duplicates":dup("source_sha256"),"derived_text_duplicates":dup("snapshot_sha256"),"case_selection_allowed":False,"source_only_schema_changed":False,"semantic_rules_changed":False,"automatic_merge":False,"merge_performed":False,"sources":receipts}
    (out/"ROOT_RECEIPT.json").write_text(json.dumps(root,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"SUMMARY.txt").write_text("\n".join([f"STATUS={root['status']}",f"SOURCE_SUCCESS={root['source_success_count']}/{root['source_count']}",f"COMPONENT_SUCCESS={root['component_success_count']}/{root['component_count']}",f"ORIGINAL_BYTE_LOCK={root['original_byte_lock_count']}",f"DERIVED_SNAPSHOT_LOCK={root['derived_snapshot_lock_count']}","CASE_SELECTION_ALLOWED=false"])+"\n",encoding="utf-8")
    print((out/"SUMMARY.txt").read_text()); return 0 if not bad else 2

if __name__=="__main__": sys.exit(main())
