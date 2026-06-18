# -*- coding: utf-8 -*-
"""보육나침반 공식자료 색인 생성기.
- 텍스트 PDF: PyMuPDF로 페이지별 텍스트 추출
- 이미지형 PDF: 기본 OCR(선택)로 페이지별 텍스트 추출

사용:
  python scripts/ingest_documents.py
  ENABLE_OCR=true python scripts/ingest_documents.py
"""
import fitz, os, json, re, pathlib, time, subprocess, tempfile, shutil
BASE = pathlib.Path(__file__).resolve().parents[1]
RAW = BASE / "data" / "raw"
OUT = BASE / "data" / "index"
OUT.mkdir(parents=True, exist_ok=True)
ENABLE_OCR = os.environ.get("ENABLE_OCR", "false").lower() in {"1","true","yes","y"}
OCR_LANG = os.environ.get("OCR_LANG", "Hangul+eng")
OCR_DPI_SCALE = float(os.environ.get("OCR_DPI_SCALE", "1.7"))
DOCUMENTS = [
    (RAW/"1. 2026년도 보육사업안내_본문.pdf", "2026년도 보육사업안내 본문", "policy_guide_main"),
    (RAW/"2. 2026년도 보육사업안내_부록.pdf", "2026년도 보육사업안내 부록", "policy_guide_appendix"),
    (RAW/"2024 개정 표준보육과정(0~2세) 0-1세 실행자료.pdf", "2024 개정 표준보육과정 0·1세 실행자료", "curriculum_0_1"),
    (RAW/"2024 개정 표준보육과정(0~2세) 2세 실행자료.pdf", "2024 개정 표준보육과정 2세 실행자료", "curriculum_2"),
    (RAW/"2024 개정 표준보육과정(0~2세) 해설서.pdf", "2024 개정 표준보육과정 해설서", "curriculum_commentary"),
    (RAW/"2024+개정+어린이집+평가+매뉴얼.pdf", "2024 개정 어린이집 평가 매뉴얼", "evaluation_manual"),
    (RAW/"2025 어린이집 재무회계 매뉴얼.pdf", "2025 어린이집 재무회계 매뉴얼", "finance_manual"),
    (RAW/"누리과정(놀이실행자료)-확인용.pdf", "2019 개정 누리과정 놀이실행자료", "nuri_play"),
]

def clean(txt):
    txt=(txt or '').replace('\x00','')
    txt=txt.replace('\u200b','')
    txt=re.sub(r'[ \t]+',' ',txt)
    txt=re.sub(r'\n{3,}','\n\n',txt)
    return txt.strip()

def chunk_text(text, max_chars=1500, overlap=180):
    text=clean(text)
    if not text: return []
    paras=[p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    chunks=[]; cur=''
    for p in paras:
        if len(cur)+len(p)+2 <= max_chars:
            cur=(cur+'\n\n'+p).strip()
        else:
            if cur: chunks.append(cur)
            if len(p)>max_chars:
                start=0
                while start<len(p):
                    chunks.append(p[start:start+max_chars])
                    start += max_chars-overlap
                cur=''
            else:
                cur=p
    if cur: chunks.append(cur)
    return chunks

def ocr_page(page):
    if shutil.which('tesseract') is None:
        return ''
    with tempfile.TemporaryDirectory() as td:
        img = pathlib.Path(td)/'page.png'
        pix = page.get_pixmap(matrix=fitz.Matrix(OCR_DPI_SCALE, OCR_DPI_SCALE), alpha=False)
        pix.save(str(img))
        try:
            res = subprocess.run(['tesseract', str(img), 'stdout', '-l', OCR_LANG, '--psm', '6'], capture_output=True, text=True, timeout=45)
            return clean(res.stdout)
        except Exception as e:
            return f"[OCR_ERROR] {type(e).__name__}: {e}"

jsonl=OUT/'childcare_chunks.jsonl'; summary=[]
with open(jsonl,'w',encoding='utf-8') as out:
    for path,title,cat in DOCUMENTS:
        if not path.exists():
            summary.append({'doc_title':title,'category':cat,'status':'missing','path':str(path)})
            continue
        st=time.time(); doc=fitz.open(str(path)); pages=len(doc); chars=0; empty=[]; chunks_count=0; ocr_pages=0
        for i,page in enumerate(doc,start=1):
            text=clean(page.get_text('text') or '')
            if len(text)<20 and ENABLE_OCR:
                text=ocr_page(page)
                if text: ocr_pages += 1
            chars+=len(text)
            if len(text)<20: empty.append(i)
            lines=[ln.strip() for ln in text.splitlines() if ln.strip()]
            section=' / '.join(lines[:2])[:120] if lines else ''
            for j,ch in enumerate(chunk_text(text),start=1):
                rec={'doc_title':title,'category':cat,'source_file':path.name,'page':i,'chunk_index':j,'section_hint':section,'text':ch,'keywords':[]}
                out.write(json.dumps(rec,ensure_ascii=False)+'\n'); chunks_count+=1
        summary.append({'doc_title':title,'category':cat,'status':'ok','pages':pages,'chars':chars,'empty_or_low_text_pages':empty[:80],'empty_count':len(empty),'ocr_pages':ocr_pages,'chunks':chunks_count,'seconds':round(time.time()-st,2)})
(OUT/'ingest_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(jsonl)
print(json.dumps(summary,ensure_ascii=False,indent=2))
