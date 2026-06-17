# -*- coding: utf-8 -*-
"""
보육나침반 — 근거 기반 보육행정 MCP 서버
=========================================
목표: 흩어진 보육행정 기준을 찾아 공문·체크리스트·검토자료로 연결한다.
원칙: AI는 근거 확인과 문서화를 돕고, 최종 판단은 사람이 한다.

자료 구조
- guideline_index.json: 보육사업안내, 부록, 표준보육과정, 평가매뉴얼, 재무회계매뉴얼,
  누리과정 자료 등을 텍스트 조각으로 색인한 파일.
- 법령: 법제처 국가법령정보 API(lawSearch.do + lawService.do)로 실시간 조회.

필수 환경변수
- LAW_GO_KR_OC: 법제처 Open API OC 값. 기본값은 공모전 개발용 yatyat0404.
- LAW_DEBUG=true: 법제처 호출 실패 원인을 응답에 표시.
- PORT: streamable-http 실행 포트. 기본 8000.
- MCP_TRANSPORT=streamable-http: PlayMCP/KC 배포 시 사용.
"""

import json
import math
import os
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # 로컬 문법검사용 안전장치
    FastMCP = None  # type: ignore

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))
SERVICE_NAME = "boyuk-compass"

if FastMCP:
    mcp = FastMCP(SERVICE_NAME, host="0.0.0.0", port=PORT)
else:
    class _DummyMCP:
        def tool(self):
            def deco(fn):
                return fn
            return deco
        def run(self, *args, **kwargs):
            return None
    mcp = _DummyMCP()

TODAY = date.today().isoformat()
LAW_OC = os.environ.get("LAW_GO_KR_OC", "yatyat0404").strip()
LAW_DEBUG = os.environ.get("LAW_DEBUG", "false").lower() in {"1", "true", "yes", "y"}

# ──────────────────────────────────────────────────────────────
# 1. 문서 색인 로딩
# ──────────────────────────────────────────────────────────────
INDEX_CANDIDATES = [
    os.path.join(HERE, "guideline_index.json"),
    os.path.join(HERE, "data", "index", "childcare_chunks.json"),
    os.path.join(HERE, "data", "index", "childcare_chunks.jsonl"),
]

DOC_CATEGORY_ALIASES = {
    "보육사업안내": ["보육사업", "사업안내", "2026", "본문", "부록"],
    "보육사업안내 본문": ["보육사업안내 본문", "사업안내 본문", "본문"],
    "보육사업안내 부록": ["보육사업안내 부록", "사업안내 부록", "부록"],
    "표준보육과정": ["표준보육", "보육과정", "0·1세", "0-1세", "2세", "해설서", "실행자료"],
    "0·1세 실행자료": ["0·1세", "0-1세", "0.1세", "영아", "실행자료"],
    "2세 실행자료": ["2세", "실행자료"],
    "해설서": ["해설서", "표준보육과정 해설"],
    "평가매뉴얼": ["평가", "평가제", "평가매뉴얼", "어린이집 평가"],
    "재무회계": ["재무", "회계", "재무회계", "지출", "예산", "결산", "계정"],
    "누리과정": ["누리", "놀이실행", "3-5세", "유아"],
}

REQUIRED_DOCS = [
    "2026년도 보육사업안내 본문",
    "2026년도 보육사업안내 부록",
    "2024 개정 표준보육과정 0·1세 실행자료",
    "2024 개정 표준보육과정 2세 실행자료",
    "2024 개정 표준보육과정 해설서",
    "2024 개정 어린이집 평가 매뉴얼",
    "어린이집 재무매뉴얼",
    "누리과정 놀이실행자료",
]


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_json_or_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        if path.endswith(".jsonl"):
            rows = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
            return rows
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("chunks", "items", "data", "documents"):
                if isinstance(data.get(key), list):
                    return [x for x in data[key] if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _coerce_chunk(item: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """기존 guideline_index.json 형식도 새 색인 형식으로 통일."""
    source = _normalize_text(item.get("source") or item.get("doc_title") or item.get("title") or "지침서")
    text = _normalize_text(item.get("text") or item.get("content") or item.get("body") or "")
    doc_title = _normalize_text(item.get("doc_title") or item.get("document") or source)
    category = _normalize_text(item.get("category") or item.get("type") or _infer_category(doc_title + " " + source))
    page = item.get("page") or item.get("page_no") or item.get("쪽수") or ""
    section = _normalize_text(item.get("section") or item.get("heading") or item.get("chapter") or "")
    keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else []
    return {
        "chunk_id": item.get("chunk_id") or f"chunk_{idx:06d}",
        "doc_id": item.get("doc_id") or _slugify(doc_title or source),
        "doc_title": doc_title or source,
        "category": category or "기타",
        "source": source,
        "page": str(page) if page else "",
        "section": section,
        "keywords": [str(k) for k in keywords],
        "text": text,
    }


def _slugify(s: str) -> str:
    s = re.sub(r"[^가-힣A-Za-z0-9]+", "_", s).strip("_")
    return s[:80] or "document"


def _infer_category(value: str) -> str:
    v = str(value)
    for cat, keys in DOC_CATEGORY_ALIASES.items():
        if any(k in v for k in keys):
            return cat
    return "기타"


def _load_guideline_index() -> List[Dict[str, Any]]:
    raw: List[Dict[str, Any]] = []
    for p in INDEX_CANDIDATES:
        raw = _load_json_or_jsonl(p)
        if raw:
            break
    chunks = [_coerce_chunk(item, idx) for idx, item in enumerate(raw)]
    return [c for c in chunks if c.get("text")]


GUIDELINE_INDEX = _load_guideline_index()

# ──────────────────────────────────────────────────────────────
# 2. 검색 엔진: 키워드 + n-gram + 문서분류 필터
# ──────────────────────────────────────────────────────────────
STOPWORDS = {
    "있는", "하는", "해야", "되는", "관련", "대한", "그리고", "어떻게", "무엇", "알려", "지침", "법령", "근거",
    "확인", "이것", "저것", "거야", "인지", "되나", "되어", "해주세요", "해줘", "어린이집", "보육", "행정"
}

SYNONYMS = {
    "부모": ["학부모", "보호자"],
    "학부모": ["보호자", "부모"],
    "보호자": ["학부모", "부모"],
    "교사": ["보육교사", "교직원", "담임"],
    "교직원": ["보육교사", "교사", "보육교직원"],
    "채용": ["임용", "자격", "결격", "범죄경력", "아동학대"],
    "회계": ["재무", "예산", "결산", "계정", "지출", "증빙"],
    "지출": ["집행", "계정", "예산", "증빙"],
    "급식": ["위생", "식단", "간식", "재료"],
    "안전": ["점검", "사고", "비상", "재해", "소방", "수질"],
    "운영위원회": ["운영위", "위원회", "보호자위원", "학부모위원"],
    "평가": ["평가제", "평가매뉴얼", "지표", "관찰", "상호작용"],
    "놀이": ["배움", "지원", "표준보육과정", "영역"],
    "건강검진": ["영유아건강검진", "검진", "미수검"],
    "감염병": ["수족구", "등원중지", "전염", "예방"],
    "고용보험": ["실업급여", "육아휴직급여", "출산전후휴가급여", "모성보호", "피보험자", "상실", "취득", "보험료"],
    "사대보험": ["4대보험", "고용보험", "산재보험", "건강보험", "국민연금", "취득신고", "상실신고"],
    "4대보험": ["사대보험", "고용보험", "산재보험", "건강보험", "국민연금", "취득신고", "상실신고"],
    "육아휴직": ["모성보호", "육아기근로시간단축", "출산전후휴가", "고용보험", "대체교사", "휴직자"],
    "근로계약": ["근로계약서", "임금", "소정근로시간", "휴게시간", "근로조건", "계약기간"],
    "퇴사": ["상실신고", "이직확인서", "사직", "해임", "고용보험"],
}

DF: Dict[str, int] = {}
NDOCS = 0


def _tokenize(s: Any) -> List[str]:
    try:
        return [t for t in re.findall(r"[가-힣A-Za-z0-9·ㆍ\-]+", str(s)) if len(t) >= 2 and t not in STOPWORDS]
    except Exception:
        return []


def _ngrams(word: str, n: int = 2) -> List[str]:
    w = str(word)
    if len(w) < n:
        return [w] if w else []
    return [w[i:i + n] for i in range(len(w) - n + 1)]


def _build_df() -> None:
    global DF, NDOCS
    if DF:
        return
    NDOCS = len(GUIDELINE_INDEX)
    temp: Dict[str, int] = {}
    for item in GUIDELINE_INDEX:
        seen = set(_ngrams(item.get("text", ""), 2))
        for g in seen:
            temp[g] = temp.get(g, 0) + 1
    DF = temp


def _idf(g: str) -> float:
    if not DF or NDOCS <= 0:
        return 1.0
    return math.log((NDOCS + 1) / (DF.get(g, 0) + 1)) + 1.0


def _expanded_terms(query: str) -> List[str]:
    words = _tokenize(query)
    out: List[str] = []
    for w in words:
        out.append(w)
        out.extend(SYNONYMS.get(w, []))
    # 복합어 보강
    q = str(query)
    for key, vals in SYNONYMS.items():
        if key in q:
            out.extend(vals)
    seen, uniq = set(), []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _category_match_filter(category_hint: str) -> List[str]:
    if not category_hint:
        return []
    hints = [category_hint]
    for cat, aliases in DOC_CATEGORY_ALIASES.items():
        if category_hint == cat or any(a in category_hint or category_hint in a for a in aliases):
            hints.append(cat)
            hints.extend(aliases)
    return list(dict.fromkeys(hints))


def search_guidelines(query: str, topk: int = 5, category_hint: str = "") -> List[Dict[str, Any]]:
    try:
        _build_df()
        if not GUIDELINE_INDEX:
            return []
        terms = _expanded_terms(query)
        if not terms:
            return []
        cat_filters = _category_match_filter(category_hint)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        grams_by_term = {t: set(_ngrams(t, 2)) for t in terms}
        for item in GUIDELINE_INDEX:
            hay = " ".join([
                item.get("doc_title", ""), item.get("category", ""), item.get("section", ""),
                " ".join(item.get("keywords", [])), item.get("text", "")
            ])
            if cat_filters and not any(f in hay for f in cat_filters):
                continue
            score = 0.0
            matched_terms = 0
            for term, grams in grams_by_term.items():
                if term in hay:
                    score += 3.0
                    matched_terms += 1
                best = 0.0
                for g in grams:
                    if g and g in hay:
                        best = max(best, _idf(g))
                if best:
                    score += best
                    matched_terms += 0.25
            # 여러 개념을 함께 맞춘 문단 가산점
            score += min(matched_terms, 5) * 0.7
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:topk]]
    except Exception:
        return []


def _format_guideline_hit(hit: Dict[str, Any], idx: int) -> str:
    src = hit.get("doc_title") or hit.get("source") or "지침서"
    page = f" p.{hit.get('page')}" if hit.get("page") else ""
    section = f" / {hit.get('section')}" if hit.get("section") else ""
    text = _normalize_text(hit.get("text", ""))[:800]
    return f"{idx}. {src}{page}{section}\n   {text}"

# ──────────────────────────────────────────────────────────────
# 3. 법제처 API: 검색 → 본문 조회 → 조문 검색
# ──────────────────────────────────────────────────────────────
IMPORTANT_LAWS = [
    # 보육기관 운영 기본 법령
    "영유아보육법",
    "영유아보육법 시행령",
    "영유아보육법 시행규칙",
    "사회복지사업법",
    "사회복지법인 및 사회복지시설 재무ㆍ회계 규칙",
    "아동복지법",
    "개인정보 보호법",
    "감염병의 예방 및 관리에 관한 법률",
    # 사업장·인사·4대보험·모성보호 관련 필수 법령
    "근로기준법",
    "근로기준법 시행령",
    "근로기준법 시행규칙",
    "고용보험법",
    "고용보험법 시행령",
    "고용보험법 시행규칙",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행규칙",
    "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률",
    "국민연금법",
    "국민건강보험법",
    "산업재해보상보험법",
]


def _law_debug_msg(msg: str) -> List[Dict[str, str]]:
    if LAW_DEBUG:
        return [{"law_name": "[디버그]", "message": msg}]
    return []


def _http_get_json(url: str, params: Dict[str, Any], timeout: float = 7.0) -> Tuple[Optional[Any], str]:
    try:
        import httpx
        r = httpx.get(url, params=params, timeout=timeout)
        text = r.text
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {text[:500]}"
        try:
            return r.json(), ""
        except Exception:
            return None, f"JSON 파싱 실패: {text[:800]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)}"


def _walk_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


def _first_value(d: Dict[str, Any], keys: List[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def search_law_candidates(query: str, topk: int = 5) -> List[Dict[str, str]]:
    """법령명 검색. MST/법령ID까지 확보한다."""
    if not LAW_OC:
        return _law_debug_msg("LAW_GO_KR_OC 환경변수가 비어 있습니다.")
    params = {"OC": LAW_OC, "target": "law", "type": "JSON", "query": str(query)}
    data, err = _http_get_json("https://www.law.go.kr/DRF/lawSearch.do", params)
    if err:
        return _law_debug_msg(err)

    candidates: List[Dict[str, str]] = []
    for d in _walk_dicts(data):
        name = _first_value(d, ["법령명한글", "법령명", "법령명한글명", "lawName"])
        mst = _first_value(d, ["MST", "법령일련번호", "mst"])
        law_id = _first_value(d, ["법령ID", "lawId", "ID"])
        promulgation = _first_value(d, ["공포일자", "promulgationDate"])
        enforcement = _first_value(d, ["시행일자", "enforcementDate"])
        ministry = _first_value(d, ["소관부처명", "소관부처", "ministry"])
        if name:
            candidates.append({
                "law_name": name,
                "mst": mst,
                "law_id": law_id,
                "promulgation_date": promulgation,
                "enforcement_date": enforcement,
                "ministry": ministry,
            })
    seen, uniq = set(), []
    for c in candidates:
        key = (c.get("law_name"), c.get("mst"), c.get("law_id"))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq[:topk]


def get_law_detail(mst: str = "", law_id: str = "") -> Tuple[Optional[Any], str]:
    """법령 본문 JSON 조회."""
    if not LAW_OC:
        return None, "LAW_GO_KR_OC 환경변수가 비어 있습니다."
    params: Dict[str, Any] = {"OC": LAW_OC, "target": "law", "type": "JSON"}
    if mst:
        params["MST"] = mst
    elif law_id:
        params["ID"] = law_id
    else:
        return None, "MST 또는 법령ID가 없습니다."
    return _http_get_json("https://www.law.go.kr/DRF/lawService.do", params, timeout=9.0)


def _extract_articles(law_json: Any) -> List[Dict[str, str]]:
    articles: List[Dict[str, str]] = []
    for d in _walk_dicts(law_json):
        # 법제처 조문 키 변형 대응
        content = _first_value(d, ["조문내용", "조문내용문", "내용", "articleContent"])
        title = _first_value(d, ["조문제목", "제목", "articleTitle"])
        number = _first_value(d, ["조문번호", "조번호", "articleNo"])
        branch = _first_value(d, ["조문가지번호", "가지번호"])
        if content or title:
            no = number + (("의" + branch) if branch and branch != "0" else "")
            articles.append({"article_no": no, "title": title, "content": _normalize_text(content)})
    # 중복 제거
    seen, uniq = set(), []
    for a in articles:
        key = (a.get("article_no"), a.get("title"), a.get("content")[:80])
        if key not in seen:
            seen.add(key)
            uniq.append(a)
    return uniq


def _score_article(article: Dict[str, str], terms: List[str]) -> float:
    hay = " ".join([article.get("article_no", ""), article.get("title", ""), article.get("content", "")])
    score = 0.0
    for t in terms:
        if t in hay:
            score += 3.0
        for g in _ngrams(t, 2):
            if g and g in hay:
                score += 0.4
    return score


def search_law_articles(query: str, law_name: str = "", topk: int = 3) -> List[Dict[str, str]]:
    """법령명 후보를 찾고, 첫 후보의 본문에서 관련 조문을 검색한다."""
    search_query = law_name or _guess_law_query(query)
    candidates = search_law_candidates(search_query, topk=4)
    if not candidates or candidates[0].get("law_name") == "[디버그]":
        return candidates

    results: List[Dict[str, str]] = []
    terms = _expanded_terms(query)
    for cand in candidates:
        data, err = get_law_detail(cand.get("mst", ""), cand.get("law_id", ""))
        if err:
            if LAW_DEBUG:
                results.append({"law_name": cand.get("law_name", ""), "article": "[본문조회 오류]", "content": err})
            continue
        articles = _extract_articles(data)
        scored = sorted((( _score_article(a, terms), a) for a in articles), key=lambda x: -x[0])
        picked = [a for score, a in scored if score > 0][:topk]
        if not picked and articles:
            picked = articles[:1]
        for a in picked:
            results.append({
                "law_name": cand.get("law_name", ""),
                "mst": cand.get("mst", ""),
                "law_id": cand.get("law_id", ""),
                "article_no": a.get("article_no", ""),
                "title": a.get("title", ""),
                "content": a.get("content", "")[:1000],
            })
        if results:
            break
    return results[:topk]


def _guess_law_query(query: str) -> str:
    q = str(query)
    # 사업장·인사·4대보험·모성보호 질문은 보육행정에서도 매우 빈번하므로 우선 분기
    if any(k in q for k in ["고용보험법 시행규칙", "고용보험 시행규칙"]):
        return "고용보험법 시행규칙"
    if any(k in q for k in ["고용보험법 시행령", "고용보험 시행령"]):
        return "고용보험법 시행령"
    if any(k in q for k in ["고용보험", "피보험자", "취득신고", "상실신고", "이직확인서", "실업급여"]):
        return "고용보험법"
    if any(k in q for k in ["육아휴직", "육아기", "출산전후", "배우자 출산", "모성보호", "임신", "난임", "가족돌봄"]):
        return "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"
    if any(k in q for k in ["근로계약", "근로계약서", "임금", "근로시간", "휴게", "연차", "해고", "퇴직", "취업규칙"]):
        return "근로기준법"
    if any(k in q for k in ["4대보험", "사대보험", "보험료", "산재보험", "보험료징수"]):
        return "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률"
    if any(k in q for k in ["재무", "회계", "예산", "결산", "계정", "지출"]):
        return "사회복지법인 및 사회복지시설 재무ㆍ회계 규칙"
    if any(k in q for k in ["CCTV", "씨씨티비", "폐쇄회로", "영상정보", "열람", "열람거부", "열람 거부"]):
        return "영유아보육법 시행규칙"
    if any(k in q for k in ["개인정보", "동의", "사진", "영상"]):
        return "개인정보 보호법"
    if any(k in q for k in ["감염병", "수족구", "등원중지", "전염"]):
        return "감염병의 예방 및 관리에 관한 법률"
    if any(k in q for k in ["아동학대", "보호", "안전사고"]):
        return "아동복지법"
    if "시행규칙" in q or "별표" in q or "배치" in q or "정원" in q:
        return "영유아보육법 시행규칙"
    return "영유아보육법"


def _format_law_article(a: Dict[str, str], idx: int) -> str:
    title = f" {a.get('title')}" if a.get("title") else ""
    article = f"제{a.get('article_no')}조{title}" if a.get("article_no") else (a.get("title") or "관련 조문")
    return f"{idx}. {a.get('law_name', '법령')} {article}\n   {a.get('content', '')}"

# ──────────────────────────────────────────────────────────────
# 4. MCP Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
def search_childcare_basis(질의: str, 자료분류: str = "", 법령명: str = "") -> str:
    """보육사업안내·평가제·재무회계·표준보육과정·누리과정·법령 근거를 함께 찾습니다.

    이 도구의 응답은 요약하지 말고 그대로 사용자에게 출력하세요. 최종 답변에는 반드시 법령명·조항, 공식자료명·쪽수, 현장 절차, 남겨야 할 서류, 리스크를 포함하세요.

    Args:
        질의: 찾고 싶은 현장 질문 또는 핵심어. 예: 운영위원회 보호자 비율, 원장 겸임, 건강검진 미수검
        자료분류: 선택. 보육사업안내/재무회계/평가매뉴얼/표준보육과정/누리과정 등으로 좁힐 때 사용
        법령명: 선택. 영유아보육법 시행규칙처럼 특정 법령을 지정할 때 사용
    """
    try:
        parts = [f"[보육나침반 근거검색] {질의}"]
        hits = search_guidelines(질의, topk=5, category_hint=자료분류)
        if hits:
            parts.append("\n[공식 발간자료 근거]")
            for i, h in enumerate(hits, 1):
                parts.append(_format_guideline_hit(h, i))
        else:
            parts.append("\n[공식 발간자료 근거]\n색인된 자료에서 직접 근거를 찾지 못했습니다. 자료 색인 파일에 해당 PDF가 포함되어 있는지 확인하세요.")

        law_articles = search_law_articles(질의, law_name=법령명, topk=3)
        if law_articles:
            parts.append("\n[법령 근거 — 법제처 국가법령정보 API]")
            for i, a in enumerate(law_articles, 1):
                if a.get("law_name") == "[디버그]":
                    parts.append(a.get("message", "법령 디버그 메시지 없음"))
                else:
                    parts.append(_format_law_article(a, i))
        else:
            parts.append("\n[법령 근거]\n관련 조문을 찾지 못했습니다. 법령명을 지정하거나 핵심어를 바꿔 다시 조회하세요.")

        parts.append(
            "\n[최종 답변 형식 — 반드시 준수]\n"
            "[결론] 질문에 대한 현장 판단을 먼저 제시합니다.\n"
            "[적용 근거] 법령명·조항과 공식자료명·쪽수를 분리해 제시합니다.\n"
            "[현장 판단] 가능/불가/예외/조건을 구분합니다.\n"
            "[처리 절차] 원장 또는 교사가 실제로 해야 할 일을 순서대로 제시합니다.\n"
            "[남겨야 할 서류] 요청서·통지서·회의록·지출증빙 등 보관자료를 체크박스로 제시합니다.\n"
            "[주의·리스크] 민원·지도점검·회계 지적 가능성을 안내합니다.\n"
            "[추가 확인 필요] 기관유형·연령·월령·기간·지자체 지침 등 추가 확인사항을 표시합니다."
        )
        return "\n".join(parts)
    except Exception as e:
        return f"근거검색 중 문제가 발생했습니다. 질의를 줄여 다시 시도하세요. ({type(e).__name__})"


# 기존 이름 호환용
@mcp.tool()
def search_law_and_guidelines(질의: str) -> str:
    """기존 호환용 도구명. 내부적으로 search_childcare_basis를 호출합니다."""
    return search_childcare_basis(질의)


@mcp.tool()
def search_law_only(질의: str, 법령명: str = "") -> str:
    """법제처 API만 사용해 관련 법령명과 조문을 조회합니다."""
    try:
        parts = [f"[법제처 법령조회] {질의}"]
        candidates = search_law_candidates(법령명 or _guess_law_query(질의), topk=5)
        if candidates:
            parts.append("\n[법령 후보]")
            for c in candidates:
                if c.get("law_name") == "[디버그]":
                    parts.append(c.get("message", ""))
                else:
                    parts.append(f"- {c.get('law_name')} / MST={c.get('mst')} / 법령ID={c.get('law_id')} / 시행일자={c.get('enforcement_date')}")
        articles = search_law_articles(질의, law_name=법령명, topk=5)
        if articles:
            parts.append("\n[관련 조문]")
            for i, a in enumerate(articles, 1):
                parts.append(_format_law_article(a, i))
        else:
            parts.append("\n관련 조문을 찾지 못했습니다. LAW_DEBUG=true로 원인을 확인하거나 법령명을 직접 지정하세요.")
        return "\n".join(parts)
    except Exception as e:
        return f"법령 조회 중 문제가 발생했습니다. ({type(e).__name__})"


ACCOUNT_TABLE = (
    "[어린이집 세출 예산 과목 구분]\n"
    "■ 인건비(100관): 원장인건비(110항), 보육교직원인건비(120항), 기타인건비(130항), 기관부담금(140항)\n"
    "■ 운영비(200관): 관리운영비(210항: 수용비및수수료·공공요금·연료비·여비·차량비·복리후생비·기타운영비), "
    "업무추진비(220항: 업무추진비·직책급·회의비)\n"
    "■ 보육활동비(300관): 기본보육활동비(310항: 교직원연수연구비·교재교구구입비·행사비·영유아복리비·급식간식재료비)\n"
    "■ 수익자부담경비(400관): 특별활동비지출, 기타필요경비지출\n"
    "■ 적립금(500관), 상환·반환금(600관), 재산조성비(700관), 과년도지출(800관), 잡지출(900관), 예비비(1000관)"
)


# ──────────────────────────────────────────────────────────────
# 4-1. 모든 현장 답변의 강제 출력 형식
# ──────────────────────────────────────────────────────────────
STRICT_ANSWER_ORDER = [
    "[결론]",
    "[적용 근거]",
    "[현장 판단]",
    "[처리 절차]",
    "[남겨야 할 서류]",
    "[주의·리스크]",
    "[현장 문안]",
    "[추가 확인 필요]",
]

SPECIAL_ADMIN_CASES = {
    "cctv_view_denial": {
        "keywords": ["cctv", "씨씨티비", "폐쇄회로", "영상정보", "영상", "열람", "열람거부", "열람 거부"],
        "law_hint": "영유아보육법 시행규칙",
        "category_hint": "보육사업안내 부록",
        "conclusion": "CCTV 열람은 원칙적으로 허용 방향에서 검토하고, 거부는 법령·지침상 제한 사유가 있을 때만 가능합니다.",
        "must_points": [
            "열람 장소·일시 통지는 원칙적으로 10일 이내 처리합니다.",
            "거부 사유가 있더라도 거부 사유와 불복 방법을 서면으로 통지해야 합니다.",
            "다른 아동·교직원이 촬영되었다는 사유만으로 무조건 거부하기보다, 열람 범위·시간·장소·보호조치를 조정해 검토합니다.",
            "정당한 근거 없는 거부는 보호자 민원, 지도점검, 시정명령 리스크로 이어질 수 있습니다.",
        ],
        "docs_to_keep": ["열람 요청서", "열람 통지서 또는 거부 통지서", "운영위원회 판단자료", "내부관리계획", "열람 기록대장"],
    },
    "childcare_fee_attendance": {
        "keywords": ["보육일수", "11일", "보육료", "결제", "결제조건", "출석일수", "23개월", "월령"],
        "law_hint": "영유아보육법",
        "category_hint": "보육사업안내",
        "conclusion": "보육료·출석일수 판단은 연령반, 월령, 입·퇴소일, 결석 사유, 지원유형별 예외를 함께 봐야 하므로 단순히 11일 기준만으로 단정하면 안 됩니다.",
        "must_points": [
            "아동의 실제 월령과 반 편성 기준을 먼저 확인합니다.",
            "입소·퇴소 월인지, 질병·출석인정 사유가 있는지 확인합니다.",
            "보육료 결제 가능 여부와 기관보육료·부모보육료 처리 기준을 분리해 봅니다.",
        ],
        "docs_to_keep": ["출석부", "입퇴소일 확인자료", "결석 사유 확인자료", "보육료 결제 내역", "보호자 안내 기록"],
    },
    "employment_insurance_maternity": {
        "keywords": ["고용보험", "고용보험법", "고용보험법 시행령", "고용보험법 시행규칙", "4대보험", "사대보험", "육아휴직", "육아휴직급여", "출산전후휴가", "모성보호", "육아기근로시간단축", "피보험자", "취득신고", "상실신고", "이직확인서", "근로계약", "근로계약서"],
        "law_hint": "고용보험법",
        "category_hint": "보육사업안내",
        "conclusion": "어린이집도 보육교직원을 고용하는 사업장이므로 근로계약, 4대보험, 고용보험 피보험자 신고, 육아휴직·출산전후휴가 등 모성보호 사안은 보육사업안내와 노동·고용보험 법령을 함께 확인해야 합니다.",
        "must_points": [
            "먼저 해당 교직원의 고용형태, 근로계약 기간, 소정근로시간, 입사·퇴사일, 휴직 개시·종료일을 확인합니다.",
            "고용보험 관련 사안은 고용보험법·시행령·시행규칙에서 피보험자격, 급여, 신고·확인 절차를 확인합니다.",
            "육아휴직·출산전후휴가·육아기 근로시간 단축은 남녀고용평등과 일·가정 양립 지원에 관한 법률과 고용보험 급여 규정을 함께 봅니다.",
            "어린이집 인력 공백은 보육사업안내의 보육교직원 임면보고, 대체교사, 배치기준과 함께 검토해야 합니다.",
            "보수, 휴직기간, 4대보험 처리, 복직 예정일, 대체인력 채용 여부는 서면으로 남겨야 합니다.",
        ],
        "docs_to_keep": ["근로계약서", "임면보고 자료", "4대보험 취득·상실 신고자료", "육아휴직 또는 출산전후휴가 신청서", "휴직·복직 확인서", "급여대장", "대체교사 또는 대체인력 관련 서류", "보육통합정보시스템 인력변동 기록"],
    },
    "finance_expense": {
        "keywords": ["회식", "업무추진비", "회의비", "관항목", "관 항 목", "추경", "전용", "집행률", "지출", "계정과목"],
        "law_hint": "사회복지법인 및 사회복지시설 재무ㆍ회계 규칙",
        "category_hint": "재무회계",
        "conclusion": "재무회계는 지출 목적을 먼저 확정한 뒤 관·항·목, 예산 편성 여부, 목적 외 사용 여부, 전용·추경 가능 여부, 증빙자료를 순서대로 판단해야 합니다.",
        "must_points": [
            "지출 목적이 교직원 복리후생인지, 회의 운영인지, 대외 업무추진인지 먼저 구분합니다.",
            "세출예산에 편성된 관·항·목 범위 안에서 집행합니다.",
            "예산 목적 외 사용금지와 전용 제한 여부를 확인합니다.",
            "회의비·업무추진비는 회의록, 참석자, 목적, 영수증 등 증빙이 특히 중요합니다.",
        ],
        "docs_to_keep": ["지출결의서", "품의서", "영수증·카드전표", "참석자 명단", "회의록", "거래명세서", "예산서·추경예산서"],
    },
    "play_curriculum": {
        "keywords": ["놀이", "배움", "배움읽기", "5개 영역", "표준보육", "누리", "놀이지원", "놀이흐름"],
        "law_hint": "",
        "category_hint": "표준보육과정",
        "conclusion": "놀이 기록은 활동명을 예쁘게 쓰는 것이 아니라 영유아의 몸짓·말·표정·관계·탐색에서 배움을 읽고, 5개 영역과 교사의 지원을 연결해 해석해야 합니다.",
        "must_points": [
            "연령을 먼저 구분합니다: 0·1세, 2세, 3~5세.",
            "관찰 사실과 교사의 해석을 분리합니다.",
            "5개 영역은 억지로 모두 넣기보다 놀이에서 실제로 드러난 영역을 중심으로 연결합니다.",
            "다음 놀이는 교사가 끌고 가는 활동이 아니라 영유아의 흥미가 이어질 수 있는 공간·자료·상호작용 지원으로 제안합니다.",
        ],
        "docs_to_keep": ["놀이관찰 기록", "사진 또는 일화기록", "교사 지원 기록", "다음 놀이 계획", "보육과정 평가 기록"],
    },
}


def _detect_special_case(query: str) -> Optional[Dict[str, Any]]:
    q = str(query or "").lower()
    for case in SPECIAL_ADMIN_CASES.values():
        if any(str(k).lower() in q for k in case.get("keywords", [])):
            return case
    return None


def _source_line_from_hit(hit: Dict[str, Any]) -> str:
    src = hit.get("doc_title") or hit.get("source") or "공식자료"
    page = f" p.{hit.get('page')}" if hit.get("page") else " 쪽수 미표시"
    section = f" / {hit.get('section')}" if hit.get("section") else ""
    return f"- {src}{page}{section}"


def _law_line_from_article(a: Dict[str, str]) -> str:
    if a.get("law_name") == "[디버그]":
        return "- 법제처 조회 디버그: " + a.get("message", "")
    title = f" {a.get('title')}" if a.get("title") else ""
    article = f"제{a.get('article_no')}조{title}" if a.get("article_no") else (a.get("title") or "관련 조문")
    return f"- {a.get('law_name', '법령')} {article}: {_normalize_text(a.get('content', ''))[:350]}"


def _build_strict_answer(query: str, context: str = "", category_hint: str = "", law_hint: str = "") -> str:
    """모든 행정 답변을 결론-근거-판단-절차-서류-리스크 구조로 강제한다."""
    case = _detect_special_case(" ".join([query, context, category_hint, law_hint]))
    effective_category = category_hint or (case or {}).get("category_hint", "")
    effective_law = law_hint or (case or {}).get("law_hint", "")

    q = " ".join([query, context]).strip()
    hits = search_guidelines(q, topk=6, category_hint=effective_category)
    laws = search_law_articles(q, law_name=effective_law, topk=4) if effective_law or q else []

    conclusion = (case or {}).get("conclusion") or "먼저 공식자료와 법령 근거를 확인한 뒤, 기관 상황에 맞게 처리해야 합니다. 근거가 확인되지 않은 내용은 단정하지 않습니다."
    must_points = (case or {}).get("must_points") or [
        "질문의 대상, 기간, 연령, 비용 재원, 기관유형을 먼저 확인합니다.",
        "공식자료 근거와 법령 근거를 분리하여 확인합니다.",
        "예외 규정은 적용 조건이 맞는 경우에만 안내합니다.",
    ]
    docs = (case or {}).get("docs_to_keep") or ["관련 요청서", "검토 기록", "통지 또는 안내 기록", "근거자료 출력본", "내부 결재자료"]

    parts: List[str] = []
    parts.append("[보육나침반 현장답변]")
    parts.append(f"질문: {query}")
    if context:
        parts.append(f"추가상황: {context}")

    parts.append("\n[결론]")
    parts.append(conclusion)

    parts.append("\n[적용 근거]")
    if laws:
        parts.append("■ 법령")
        for a in laws:
            parts.append(_law_line_from_article(a))
    else:
        parts.append("■ 법령: 법제처 API에서 직접 조문을 찾지 못했습니다. 법령명 또는 핵심어를 더 구체화해 재조회가 필요합니다.")
    if hits:
        parts.append("■ 공식자료")
        for h in hits[:5]:
            parts.append(_source_line_from_hit(h))
    else:
        parts.append("■ 공식자료: 색인된 보육사업안내·부록·매뉴얼에서 직접 근거를 찾지 못했습니다. 색인 누락 여부를 확인하세요.")

    parts.append("\n[현장 판단]")
    for p in must_points:
        parts.append(f"- {p}")

    parts.append("\n[처리 절차]")
    parts.append("1. 요청 또는 상황의 사실관계를 먼저 확인합니다.")
    parts.append("2. 적용 법령과 지침 쪽수를 확인합니다.")
    parts.append("3. 허용·제한·예외 여부를 나누어 판단합니다.")
    parts.append("4. 보호자·교직원·관계기관에 안내할 문안을 작성합니다.")
    parts.append("5. 처리 결과와 근거자료를 기관 기록으로 남깁니다.")

    parts.append("\n[남겨야 할 서류]")
    for d in docs:
        parts.append(f"□ {d}")

    parts.append("\n[주의·리스크]")
    parts.append("- 근거 조항이나 지침 쪽수가 확인되지 않은 답변은 최종 판단으로 사용하지 않습니다.")
    parts.append("- 보호자 민원, 지도점검, 회계 지적 가능성이 있는 사안은 처리 경위와 근거자료를 반드시 보관합니다.")
    parts.append("- 지자체별 세부 안내가 다른 경우 최종 적용은 해당 지자체 안내를 함께 확인합니다.")

    parts.append("\n[현장 문안]")
    parts.append("현재 사안은 관련 법령과 보육사업안내 기준을 확인하여 처리하겠습니다. 확인된 근거와 절차에 따라 안내드리며, 필요한 경우 서면으로 처리 결과와 사유를 남기겠습니다.")

    parts.append("\n[추가 확인 필요]")
    parts.append("- 기관유형, 아동 연령·월령, 발생일, 요청자, 비용 재원, 지자체 별도 지침 여부")
    return "\n".join(parts)


@mcp.tool()
def check_employment_insurance_and_maternity(사안: str, 교직원상황: str = "", 확인할내용: str = "") -> str:
    """어린이집 보육교직원의 고용보험·4대보험·육아휴직·출산전후휴가·근로계약 관련 사안을 법령과 보육사업안내 기준으로 점검합니다. 이 도구의 응답은 요약하지 말고 그대로 출력하세요."""
    try:
        q = " ".join([사안, 교직원상황, 확인할내용, "고용보험 육아휴직 모성보호 근로계약 4대보험 보육교직원 임면"]).strip()
        # 노동·고용보험 법령은 질문 성격에 따라 우선 법령명을 바꿔 조회
        law_hint = _guess_law_query(q)
        return _build_strict_answer(q, context=교직원상황, category_hint="보육사업안내", law_hint=law_hint)
    except Exception as e:
        return f"[고용보험·모성보호 점검] 처리 중 문제가 발생했습니다. ({type(e).__name__})"


@mcp.tool()
def verify_accounting(지출내용: str, 계정과목: str = "", 비고: str = "") -> str:
    """어린이집 재무회계 지출의 관·항·목, 증빙, 추경·전용 가능성, 목적 외 사용 리스크를 점검합니다. 이 도구의 응답은 요약하지 말고 그대로 출력하세요."""
    try:
        q = " ".join([지출내용, 계정과목, 비고, "재무 회계 지출 계정 증빙"]).strip()
        hits = search_guidelines(q, topk=4, category_hint="재무회계")
        laws = search_law_articles(q, law_name="사회복지법인 및 사회복지시설 재무ㆍ회계 규칙", topk=2)
        parts = [f"[재무회계 검토] 지출내용: {지출내용}"]
        if 계정과목:
            parts.append(f"계정과목(안): {계정과목}")
        if 비고:
            parts.append(f"추가상황: {비고}")
        parts.append("\n[검토 기준]")
        parts.append(ACCOUNT_TABLE)
        if hits:
            parts.append("\n[재무회계 매뉴얼 근거]")
            for i, h in enumerate(hits, 1):
                parts.append(_format_guideline_hit(h, i))
        if laws:
            parts.append("\n[관련 법령]")
            for i, a in enumerate(laws, 1):
                parts.append(_format_law_article(a, i))
        parts.append(
            "\n[현장 확인 체크]\n"
            "□ 지출 성격에 맞는 관>항>목 3단계로 표기했는가\n"
            "□ 예산 편성 항목과 집행 항목이 일치하는가\n"
            "□ 세금계산서·카드전표·견적서·거래명세서 등 증빙이 있는가\n"
            "□ 보조금·필요경비·수익자부담경비 목적 외 사용 소지가 없는가\n"
            "□ 판단이 애매하면 지자체 또는 회계 담당자 확인 기록을 남겼는가"
        )
        return "\n".join(parts)
    except Exception as e:
        return f"회계 검토 중 문제가 발생했습니다. ({type(e).__name__})"


@mcp.tool()
def create_official_document(
    문서종류: str,
    제목: str,
    핵심내용: str,
    어린이집명: str = "○○어린이집",
    원장명: str = "○○○",
    대상: str = "",
    날짜: str = "",
    근거질의: str = "",
) -> str:
    """어린이집 공문·협조요청서·안내문·회의록 초안을 생성합니다."""
    try:
        d = 날짜 or TODAY
        kind = str(문서종류).replace(" ", "")
        basis = ""
        if 근거질의:
            basis = "\n\n[작성 참고 근거]\n" + search_childcare_basis(근거질의)[:1800]

        if kind in {"협조공문", "공문", "자료요청", "자료제출요청"}:
            target = 대상 or "관계기관"
            return (
                f"[협조공문 초안]\n\n문서번호: {어린이집명}-2026-00\n시행일자: {d}\n수    신: {target}\n발    신: {어린이집명}\n제    목: {제목}\n\n"
                f"1. 귀 기관의 협조에 감사드립니다.\n\n"
                f"2. {핵심내용}\n\n"
                f"3. 관련 자료는 어린이집 운영 및 행정 확인을 위한 자료로 활용될 예정이오니 협조하여 주시기 바랍니다.\n\n"
                f"붙임: 필요 시 기재.  끝.\n\n{어린이집명} 원장 {원장명}"
                f"{basis}"
            )
        if kind in {"가정통신문", "안내문", "보호자안내"}:
            target = 대상 or "학부모님"
            return (
                f"[가정통신문 초안]\n\n제목: {제목}\n\n{target}께\n\n"
                f"{핵심내용}\n\n"
                f"가정에서도 함께 확인해 주시기 바라며, 문의사항은 어린이집으로 연락해 주시기 바랍니다.\n\n"
                f"{d}\n{어린이집명} 원장 {원장명}{basis}"
            )
        if kind in {"공지", "공지사항", "교직원공지"}:
            target = 대상 or "교직원"
            return f"[공지 초안]\n\n수신: {target}\n일자: {d}\n제목: {제목}\n\n{핵심내용}\n\n위 내용을 확인하여 업무에 반영해 주시기 바랍니다.\n\n{어린이집명}{basis}"
        if kind in {"운영위원회회의록", "운영위원회"}:
            return (
                f"[{어린이집명} 운영위원회 회의록 초안]\n\n1. 일시: {d}\n2. 장소:\n3. 참석자:\n4. 안건: {제목}\n5. 논의내용:\n   {핵심내용}\n6. 결정사항:\n7. 기타사항:\n\n작성자:        확인: 원장 {원장명}{basis}"
            )
        return "지원 문서종류: 협조공문/자료요청/가정통신문/공지사항/운영위원회회의록 입니다."
    except Exception as e:
        return f"문서 생성 중 문제가 발생했습니다. ({type(e).__name__})"


@mcp.tool()
def make_childcare_admin_checklist(업무상황: str, 자료분류: str = "", 마감일: str = "") -> str:
    """현장 상황에 맞는 행정 체크리스트와 필요 문서를 생성합니다."""
    try:
        basis = search_childcare_basis(업무상황, 자료분류=자료분류)[:2200]
        due = f"\n마감/기한: {마감일}" if 마감일 else ""
        return (
            f"[보육행정 체크리스트] {업무상황}{due}\n\n"
            "1. 상황 확인\n□ 대상 아동·교직원·기관 범위를 확인한다.\n□ 관련 법령·지침·평가제 기준을 확인한다.\n□ 지자체 또는 관계기관 확인이 필요한 항목을 구분한다.\n\n"
            "2. 문서·자료 준비\n□ 공문 또는 안내문 초안을 작성한다.\n□ 보호자 안내가 필요한 경우 안내 일자와 방법을 기록한다.\n□ 회계·안전·건강 관련 증빙자료를 보관한다.\n\n"
            "3. 실행 및 기록\n□ 담당자와 처리기한을 정한다.\n□ 처리 결과와 회신 여부를 기록한다.\n□ 추후 평가제·운영점검에서 확인 가능한 형태로 보관한다.\n\n"
            "4. 재점검\n□ 누락 서류가 없는지 확인한다.\n□ 민원 소지가 있는 표현은 사실 중심으로 수정한다.\n□ 최종 제출 전 원장 또는 담당자가 확인한다.\n\n"
            f"[관련 근거 요약]\n{basis}"
        )
    except Exception as e:
        return f"체크리스트 생성 중 문제가 발생했습니다. ({type(e).__name__})"


REQUIRED_FIELDS = {
    "가정통신문": ["제목", "안내 목적", "구체 일정", "협조사항", "문의처", "발신일자", "어린이집명"],
    "협조공문": ["수신처", "제목", "요청사항", "제출기한", "붙임", "발신일자", "기관명"],
    "운영위원회회의록": ["일시", "장소", "참석자", "안건", "논의내용", "결정사항", "작성자/확인자"],
    "공지사항": ["제목", "대상", "핵심내용", "기한", "담당자", "발신일자"],
}

RISKY_PHRASES = {
    "어쩔 수 없습니다": "현재 상황을 확인하고 필요한 조치를 진행하겠습니다",
    "책임질 수 없습니다": "기관에서 확인 가능한 범위 내에서 절차에 따라 안내드리겠습니다",
    "아이들이 그럴 수 있습니다": "영유아의 발달 특성을 고려하되, 재발 방지를 위해 세심히 지원하겠습니다",
    "무조건": "관련 기준과 상황을 확인한 후",
    "절대": "가능한 범위에서",
}


@mcp.tool()
def review_admin_document(문서내용: str, 문서종류: str = "가정통신문") -> str:
    """공문·공지·안내문의 누락 항목과 민원 소지 표현을 점검합니다."""
    try:
        kind = 문서종류.replace(" ", "")
        fields = REQUIRED_FIELDS.get(kind) or REQUIRED_FIELDS.get("가정통신문", [])
        text = str(문서내용)
        found, missing = [], []
        for f in fields:
            if any(tok in text for tok in _tokenize(f)):
                found.append(f)
            else:
                missing.append(f)
        risks = []
        for bad, good in RISKY_PHRASES.items():
            if bad in text:
                risks.append(f"- '{bad}' → '{good}'")
        return (
            f"[{문서종류} 문서점검]\n\n"
            f"✅ 포함된 항목: {', '.join(found) if found else '확인된 항목 없음'}\n"
            f"⚠️ 보완할 항목: {', '.join(missing) if missing else '필수 항목 대체로 포함'}\n\n"
            f"[표현 점검]\n{chr(10).join(risks) if risks else '큰 민원 소지 표현은 확인되지 않았습니다.'}\n\n"
            "[보완 원칙]\n□ 사실 중심으로 작성\n□ 기한·대상·협조사항 명확화\n□ 기관 조치사항과 보호자 협조사항 분리\n□ 최종 제출 전 근거 확인"
        )
    except Exception as e:
        return f"문서 점검 중 문제가 발생했습니다. ({type(e).__name__})"



@mcp.tool()
def map_play_to_curriculum(연령: str, 놀이상황: str, 관찰내용: str = "") -> str:
    """0·1세/2세/3~5세 놀이를 5개 영역, 배움읽기, 교사지원, 다음 놀이로 연결합니다."""
    try:
        age = str(연령)
        q = " ".join([age, 놀이상황, 관찰내용, "놀이 배움 읽기 5개 영역 교사 지원 상호작용 공간 자료 평가"]).strip()
        if any(k in age for k in ["0", "1", "영아"]):
            hint = "0·1세 실행자료"
        elif "2" in age:
            hint = "2세 실행자료"
        elif any(k in age for k in ["3", "4", "5", "유아", "누리"]):
            hint = "누리과정"
        else:
            hint = "표준보육과정"
        hits = search_guidelines(q, topk=6, category_hint=hint)
        basis = "\n".join(_format_guideline_hit(h, i) for i, h in enumerate(hits, 1)) if hits else "관련 실행자료 근거를 찾지 못했습니다. 연령과 놀이 단서를 더 구체화하세요."
        return (
            f"[놀이-보육과정 연결] 연령: {연령}\n\n"
            f"놀이상황: {놀이상황}\n"
            f"관찰내용: {관찰내용 or '별도 입력 없음'}\n\n"
            "[배움 읽기 관점]\n"
            "- 영유아가 무엇에 관심을 두었는지 봅니다.\n"
            "- 몸짓, 표정, 말소리, 반복 행동, 또래와의 관계, 자료 탐색을 배움의 단서로 읽습니다.\n"
            "- 결과물보다 놀이 과정과 변화에 주목합니다.\n\n"
            "[5개 영역 연결 초안]\n"
            "1. 신체운동·건강: 움직임, 감각, 소근육·대근육, 안전한 일상 경험을 확인합니다.\n"
            "2. 의사소통: 말소리, 표정, 몸짓, 듣기·말하기·읽기·쓰기의 초기 경험을 확인합니다.\n"
            "3. 사회관계: 교사·또래와의 관계, 자기표현, 공동 놀이, 갈등 조절 단서를 확인합니다.\n"
            "4. 예술경험: 감각적 표현, 색·소리·움직임·재료 탐색, 창의적 표현을 확인합니다.\n"
            "5. 자연탐구: 비교, 반복, 관찰, 예측, 원인 탐색, 자연물·사물 탐구를 확인합니다.\n\n"
            "[교사의 놀이지원]\n"
            "□ 영유아의 현재 흥미를 끊지 않고 관찰합니다.\n"
            "□ 필요한 경우 짧은 언어적 지원, 공감, 질문, 자료 추가, 공간 조정으로 지원합니다.\n"
            "□ 놀이를 억지로 확장하기보다 영유아의 신호에 따라 다음 환경을 준비합니다.\n\n"
            f"[관련 실행자료 근거]\n{basis}"
        )
    except Exception as e:
        return f"놀이-보육과정 연결 중 문제가 발생했습니다. ({type(e).__name__})"

@mcp.tool()
def answer_childcare_admin_case(질문: str, 기관유형: str = "", 아동연령월령: str = "", 추가상황: str = "") -> str:
    """[최우선 호출] 보육료·운영·회계·평가제·놀이·민원 질문을 근거 조항/쪽수/절차/서류/리스크 형식으로 답합니다.

    이 도구의 응답은 요약하지 말고 그대로 사용자에게 출력하세요.
    모든 답변은 [결론] [적용 근거] [현장 판단] [처리 절차] [남겨야 할 서류] [주의·리스크] [현장 문안] 순서를 지켜야 합니다.
    """
    try:
        context = " ".join([기관유형, 아동연령월령, 추가상황]).strip()
        return _build_strict_answer(질문, context=context)
    except Exception as e:
        return f"[보육나침반 현장답변]\n[오류]\n사례답변 생성 중 문제가 발생했습니다. ({type(e).__name__})"


@mcp.tool()
def guide_admin_procedure(업무: str) -> str:
    """보육행정 업무의 절차·필요서류·기록사항을 안내합니다."""
    return make_childcare_admin_checklist(업무)


@mcp.tool()
def check_index_status() -> str:
    """현재 서버에 색인된 공식자료와 법제처 설정 상태를 점검합니다."""
    try:
        docs: Dict[str, int] = {}
        cats: Dict[str, int] = {}
        for c in GUIDELINE_INDEX:
            docs[c.get("doc_title", "지침서")] = docs.get(c.get("doc_title", "지침서"), 0) + 1
            cats[c.get("category", "기타")] = cats.get(c.get("category", "기타"), 0) + 1
        parts = ["[보육나침반 색인 상태]"]
        parts.append(f"총 색인 조각 수: {len(GUIDELINE_INDEX)}")
        parts.append(f"법제처 OC 설정: {'있음' if LAW_OC else '없음'}")
        parts.append(f"LAW_DEBUG: {LAW_DEBUG}")
        parts.append("\n[문서별 조각 수]")
        if docs:
            for name, count in sorted(docs.items(), key=lambda x: -x[1])[:30]:
                parts.append(f"- {name}: {count}개")
        else:
            parts.append("- 색인 파일을 찾지 못했습니다. guideline_index.json 또는 data/index/childcare_chunks.jsonl을 배치하세요.")
        parts.append("\n[필수 자료 체크]")
        hay = " ".join(docs.keys())
        for req in REQUIRED_DOCS:
            ok = any(tok in hay for tok in _tokenize(req))
            parts.append(f"{'✅' if ok else '⚠️'} {req}")
        return "\n".join(parts)
    except Exception as e:
        return f"색인 상태 확인 중 문제가 발생했습니다. ({type(e).__name__})"


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
