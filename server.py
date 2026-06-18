# -*- coding: utf-8 -*-
"""
보육나침반 v6 — 법령·지침 근거 우선형 MCP 서버
=================================================

v6 원칙
1. 먼저 근거를 찾고, 그 다음에만 현장 판단을 쓴다.
2. 법령은 법제처 API에서 법령명 → 본문 → 조문 단위로 찾는다.
3. 지침은 공식자료 색인에서 문서명·쪽수·원문 조각을 함께 찾는다.
4. 근거가 부족하면 빈 템플릿을 채우지 않고, 단정 불가와 추가 확인사항을 명확히 쓴다.
5. 모든 현장답변은 결론·근거·판단·절차·서류·리스크·문안 순서로 출력한다.
"""

import json
import math
import os
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    FastMCP = None  # type: ignore

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))
SERVICE_NAME = "boyuk-compass"
LAW_OC = os.environ.get("LAW_GO_KR_OC", "yatyat0404").strip()
LAW_DEBUG = os.environ.get("LAW_DEBUG", "false").lower() in {"1", "true", "yes", "y"}
TODAY = date.today().isoformat()

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

# ──────────────────────────────────────────────────────────────
# 색인 로딩
# ──────────────────────────────────────────────────────────────
INDEX_FILES = [
    os.path.join(HERE, "data", "index", "childcare_chunks.jsonl"),
    os.path.join(HERE, "data", "index", "childcare_chunks.json"),
    os.path.join(HERE, "guideline_index.json"),
]

STOPWORDS = {
    "있는", "하는", "해야", "되는", "관련", "대한", "그리고", "어떻게", "무엇", "알려", "지침", "법령", "근거",
    "확인", "이것", "저것", "거야", "인지", "되나", "되어", "해주세요", "해줘", "어린이집", "보육", "행정",
    "여부", "필요", "기준", "경우", "무슨", "어떤", "하나", "되니", "하면",
}

SYNONYMS = {
    "씨씨티비": ["CCTV", "폐쇄회로", "영상정보", "영상", "열람"],
    "CCTV": ["씨씨티비", "폐쇄회로", "영상정보", "영상", "열람"],
    "열람": ["영상정보", "CCTV", "폐쇄회로", "보호자", "거부"],
    "부모": ["학부모", "보호자"],
    "학부모": ["보호자", "부모"],
    "보호자": ["학부모", "부모"],
    "교사": ["보육교사", "교직원", "담임", "보육교직원"],
    "교직원": ["보육교사", "교사", "보육교직원"],
    "보조교사": ["보조교사 지원", "임면", "근로계약", "인력", "보육교직원"],
    "채용": ["임용", "자격", "결격", "범죄경력", "아동학대", "임면"],
    "근로계약": ["근로계약서", "임금", "소정근로시간", "휴게시간", "근로조건", "계약기간", "기간제"],
    "고용보험": ["피보험자", "취득신고", "상실신고", "이직확인서", "육아휴직급여", "출산전후휴가급여"],
    "4대보험": ["사대보험", "고용보험", "산재보험", "국민연금", "건강보험", "취득신고", "상실신고"],
    "사대보험": ["4대보험", "고용보험", "산재보험", "국민연금", "건강보험", "취득신고", "상실신고"],
    "육아휴직": ["모성보호", "남녀고용평등", "육아기근로시간단축", "출산전후휴가", "휴직자", "대체교사"],
    "모성보호": ["육아휴직", "출산전후휴가", "육아기근로시간단축", "남녀고용평등"],
    "회계": ["재무", "예산", "결산", "계정", "지출", "증빙", "관", "항", "목"],
    "지출": ["집행", "계정", "예산", "증빙", "관", "항", "목"],
    "회식": ["식대", "업무추진비", "회의비", "복리후생비", "운영비", "증빙"],
    "워크숍": ["교직원연수", "연수", "식대", "행사", "운영비", "보육활동비"],
    "추경": ["추가경정예산", "예산변경", "예산전용", "운영위원회", "보고"],
    "운영위원회": ["운영위", "위원회", "보호자위원", "학부모위원", "회의록"],
    "감염병": ["수족구", "등원중지", "예방", "전염", "보고"],
    "건강검진": ["영유아건강검진", "검진", "미수검"],
    "아침돌봄": ["틈새돌봄", "조기등원", "수당", "근로시간", "임금", "지자체"],
    "아침돌봄수당": ["아침돌봄", "틈새돌봄", "조기등원", "수당", "임금", "근로시간"],
    "놀이": ["배움", "표준보육과정", "5개 영역", "상호작용", "공간", "자료"],
    "평가제": ["평가매뉴얼", "평가지표", "관찰", "면담", "기록"],
}

CATEGORY_ALIASES = {
    "보육사업안내": ["보육사업안내", "2026", "사업안내", "본문", "부록"],
    "보육사업안내 본문": ["보육사업안내 본문", "본문"],
    "보육사업안내 부록": ["보육사업안내 부록", "부록", "영상정보", "개인정보"],
    "재무회계": ["재무", "회계", "예산", "결산", "계정", "관", "항", "목"],
    "평가매뉴얼": ["평가", "평가제", "평가매뉴얼", "평가지표"],
    "표준보육과정": ["표준보육", "보육과정", "0·1세", "0-1세", "2세", "해설서", "실행자료"],
    "0·1세 실행자료": ["0·1세", "0-1세", "0.1세", "영아", "실행자료"],
    "2세 실행자료": ["2세", "실행자료"],
    "해설서": ["해설서", "표준보육과정 해설"],
    "누리과정": ["누리", "놀이실행", "3-5세", "유아"],
}

REQUIRED_DOCS = [
    "2026년도 보육사업안내 본문",
    "2026년도 보육사업안내 부록",
    "2024 개정 표준보육과정 0·1세 실행자료",
    "2024 개정 표준보육과정 2세 실행자료",
    "2024 개정 표준보육과정 해설서",
    "2024 개정 어린이집 평가 매뉴얼",
    "2025 어린이집 재무회계 매뉴얼",
    "누리과정 놀이실행자료",
]


def _clean(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]+", "_", s).strip("_")[:80] or "document"


def _infer_category(s: str) -> str:
    hay = str(s)
    for cat, keys in CATEGORY_ALIASES.items():
        if any(k in hay for k in keys):
            return cat
    return "기타"


def _read_index_file(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        if path.endswith(".jsonl"):
            rows = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            rows.append(obj)
            return rows
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for k in ("chunks", "items", "documents", "data"):
                if isinstance(data.get(k), list):
                    return [x for x in data[k] if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _coerce_chunk(item: Dict[str, Any], i: int) -> Dict[str, Any]:
    source = _clean(item.get("source") or item.get("doc_title") or item.get("title") or "공식자료")
    doc_title = _clean(item.get("doc_title") or item.get("document") or item.get("title") or source)
    text = _clean(item.get("text") or item.get("content") or item.get("body") or "")
    category = _clean(item.get("category") or item.get("type") or _infer_category(doc_title + " " + source))
    page = item.get("page") or item.get("page_no") or item.get("쪽수") or ""
    section = _clean(item.get("section") or item.get("heading") or item.get("chapter") or "")
    keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else []
    return {
        "chunk_id": item.get("chunk_id") or f"chunk_{i:06d}",
        "doc_id": item.get("doc_id") or _slug(doc_title or source),
        "doc_title": doc_title or source,
        "category": category or "기타",
        "source": source,
        "page": str(page) if page else "",
        "section": section,
        "keywords": [str(k) for k in keywords],
        "text": text,
    }


def _load_index() -> List[Dict[str, Any]]:
    raw: List[Dict[str, Any]] = []
    for path in INDEX_FILES:
        raw = _read_index_file(path)
        if raw:
            break
    chunks = [_coerce_chunk(item, i) for i, item in enumerate(raw)]
    return [c for c in chunks if c.get("text")]


GUIDELINE_INDEX = _load_index()

# ──────────────────────────────────────────────────────────────
# 검색 엔진
# ──────────────────────────────────────────────────────────────
DF: Dict[str, int] = {}
NDOCS = 0


def _tokenize(s: Any) -> List[str]:
    return [t for t in re.findall(r"[가-힣A-Za-z0-9·ㆍ\-]+", str(s)) if len(t) >= 2 and t not in STOPWORDS]


def _ngrams(word: str, n: int = 2) -> List[str]:
    w = str(word)
    if len(w) < n:
        return [w] if w else []
    return [w[i:i+n] for i in range(len(w)-n+1)]


def _build_df() -> None:
    global DF, NDOCS
    if DF:
        return
    NDOCS = len(GUIDELINE_INDEX)
    tmp: Dict[str, int] = {}
    for item in GUIDELINE_INDEX:
        seen = set(_ngrams(item.get("text", ""), 2))
        for g in seen:
            tmp[g] = tmp.get(g, 0) + 1
    DF = tmp


def _idf(g: str) -> float:
    if not DF or NDOCS <= 0:
        return 1.0
    return math.log((NDOCS + 1) / (DF.get(g, 0) + 1)) + 1.0


def _expanded_terms(query: str) -> List[str]:
    q = str(query)
    base = _tokenize(q)
    terms: List[str] = []
    for w in base:
        terms.append(w)
        terms.extend(SYNONYMS.get(w, []))
    for key, vals in SYNONYMS.items():
        if key in q:
            terms.append(key)
            terms.extend(vals)
    seen, out = set(), []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _category_filters(hint: str) -> List[str]:
    if not hint:
        return []
    out = [hint]
    for cat, aliases in CATEGORY_ALIASES.items():
        if hint == cat or any(a in hint or hint in a for a in aliases):
            out.append(cat)
            out.extend(aliases)
    return list(dict.fromkeys(out))


def search_guidelines(query: str, topk: int = 6, category_hint: str = "") -> List[Dict[str, Any]]:
    _build_df()
    if not GUIDELINE_INDEX:
        return []
    terms = _expanded_terms(query)
    if not terms:
        terms = _tokenize(query)
    if not terms:
        return []
    cat_filters = _category_filters(category_hint)
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
        matched_terms = 0.0
        for t, grams in grams_by_term.items():
            if t in hay:
                score += 5.0
                matched_terms += 1
            best = 0.0
            for g in grams:
                if g and g in hay:
                    best = max(best, _idf(g))
            if best:
                score += best
                matched_terms += 0.25
        # 문서명/쪽수 있는 자료 우대
        if item.get("page"):
            score += 0.5
        if item.get("section"):
            score += 0.3
        score += min(matched_terms, 6) * 0.9
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:topk]]


def _format_hit(hit: Dict[str, Any], i: int, limit: int = 850) -> str:
    title = hit.get("doc_title") or hit.get("source") or "공식자료"
    page = f" p.{hit.get('page')}" if hit.get("page") else " 쪽수 미표시"
    section = f" / {hit.get('section')}" if hit.get("section") else ""
    text = _clean(hit.get("text", ""))[:limit]
    return f"{i}. {title}{page}{section}\n   {text}"

# ──────────────────────────────────────────────────────────────
# 법제처 API
# ──────────────────────────────────────────────────────────────
IMPORTANT_LAWS = [
    "영유아보육법", "영유아보육법 시행령", "영유아보육법 시행규칙",
    "사회복지사업법", "사회복지법인 및 사회복지시설 재무ㆍ회계 규칙",
    "아동복지법", "개인정보 보호법", "감염병의 예방 및 관리에 관한 법률",
    "근로기준법", "근로기준법 시행령", "근로기준법 시행규칙",
    "고용보험법", "고용보험법 시행령", "고용보험법 시행규칙",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행규칙",
    "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률",
    "국민연금법", "국민건강보험법", "산업재해보상보험법",
]


def _http_get_json(url: str, params: Dict[str, Any], timeout: float = 8.0) -> Tuple[Optional[Any], str]:
    try:
        import httpx
        r = httpx.get(url, params=params, timeout=timeout)
        text = r.text
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {text[:400]}"
        try:
            return r.json(), ""
        except Exception:
            return None, f"JSON 파싱 실패: {text[:700]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)}"


def _walk(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _first(d: Dict[str, Any], keys: List[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def search_law_candidates(query: str, topk: int = 5) -> List[Dict[str, str]]:
    if not LAW_OC:
        return []
    data, err = _http_get_json(
        "https://www.law.go.kr/DRF/lawSearch.do",
        {"OC": LAW_OC, "target": "law", "type": "JSON", "query": str(query)},
    )
    if err:
        return [{"law_name": "[조회오류]", "message": err}] if LAW_DEBUG else []
    candidates: List[Dict[str, str]] = []
    for d in _walk(data):
        name = _first(d, ["법령명한글", "법령명", "법령명한글명", "lawName"])
        mst = _first(d, ["MST", "법령일련번호", "mst"])
        law_id = _first(d, ["법령ID", "lawId", "ID"])
        enforce = _first(d, ["시행일자", "enforcementDate"])
        ministry = _first(d, ["소관부처명", "소관부처", "ministry"])
        if name:
            candidates.append({"law_name": name, "mst": mst, "law_id": law_id, "enforcement_date": enforce, "ministry": ministry})
    seen, out = set(), []
    for c in candidates:
        key = (c.get("law_name"), c.get("mst"), c.get("law_id"))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:topk]


def get_law_detail(mst: str = "", law_id: str = "") -> Tuple[Optional[Any], str]:
    if not LAW_OC:
        return None, "LAW_GO_KR_OC 환경변수가 비어 있습니다."
    params: Dict[str, Any] = {"OC": LAW_OC, "target": "law", "type": "JSON"}
    if mst:
        params["MST"] = mst
    elif law_id:
        params["ID"] = law_id
    else:
        return None, "MST 또는 법령ID가 없습니다."
    return _http_get_json("https://www.law.go.kr/DRF/lawService.do", params, timeout=10.0)


def _extract_articles(law_json: Any) -> List[Dict[str, str]]:
    articles: List[Dict[str, str]] = []
    for d in _walk(law_json):
        content = _first(d, ["조문내용", "조문내용문", "내용", "articleContent"])
        title = _first(d, ["조문제목", "제목", "articleTitle"])
        number = _first(d, ["조문번호", "조번호", "articleNo"])
        branch = _first(d, ["조문가지번호", "가지번호"])
        if content or title:
            no = number + (("의" + branch) if branch and branch != "0" else "")
            articles.append({"article_no": no, "title": title, "content": _clean(content)})
    seen, out = set(), []
    for a in articles:
        key = (a.get("article_no"), a.get("title"), a.get("content")[:120])
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def _law_queries_for(question: str, specified: str = "") -> List[str]:
    q = str(question)
    if specified:
        return [specified]
    queries: List[str] = []
    if any(k in q for k in ["CCTV", "씨씨티비", "폐쇄회로", "영상정보", "영상", "열람"]):
        queries += ["영유아보육법", "영유아보육법 시행규칙", "개인정보 보호법"]
    if any(k in q for k in ["운영위원회", "운영위", "보호자위원", "위원"]):
        queries += ["영유아보육법", "영유아보육법 시행령", "영유아보육법 시행규칙"]
    if any(k in q for k in ["보육료", "보육일수", "출석", "결제", "기관보육료", "아침돌봄"]):
        queries += ["영유아보육법", "영유아보육법 시행령", "영유아보육법 시행규칙"]
    if any(k in q for k in ["재무", "회계", "예산", "결산", "추경", "전용", "관", "항", "목", "지출", "집행"]):
        queries += ["사회복지법인 및 사회복지시설 재무ㆍ회계 규칙", "영유아보육법"]
    if any(k in q for k in ["근로계약", "근로계약서", "임금", "근로시간", "휴게", "연장근로", "연차", "퇴직", "해고"]):
        queries += ["근로기준법", "근로기준법 시행령", "근로기준법 시행규칙"]
    if any(k in q for k in ["고용보험", "피보험자", "취득신고", "상실신고", "이직확인서", "실업급여"]):
        queries += ["고용보험법", "고용보험법 시행령", "고용보험법 시행규칙"]
    if any(k in q for k in ["육아휴직", "출산전후", "육아기", "모성보호", "임신", "난임", "가족돌봄"]):
        queries += ["남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "고용보험법", "고용보험법 시행령", "고용보험법 시행규칙"]
    if any(k in q for k in ["4대보험", "사대보험", "산재", "보험료", "국민연금", "건강보험"]):
        queries += ["고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률", "국민연금법", "국민건강보험법", "산업재해보상보험법"]
    if any(k in q for k in ["감염병", "수족구", "전염", "등원중지"]):
        queries += ["감염병의 예방 및 관리에 관한 법률", "영유아보육법"]
    if not queries:
        queries = ["영유아보육법", "영유아보육법 시행규칙"]
    out = []
    for x in queries:
        if x not in out:
            out.append(x)
    return out[:5]


def _score_article(article: Dict[str, str], terms: List[str]) -> float:
    hay = " ".join([article.get("article_no", ""), article.get("title", ""), article.get("content", "")])
    score = 0.0
    for t in terms:
        if t in hay:
            score += 5.0
        for g in _ngrams(t, 2):
            if g and g in hay:
                score += 0.35
    return score


def search_law_articles(question: str, law_name: str = "", topk: int = 5) -> List[Dict[str, str]]:
    terms = _expanded_terms(question) or _tokenize(question)
    results: List[Dict[str, str]] = []
    errors: List[str] = []
    for qlaw in _law_queries_for(question, law_name):
        candidates = search_law_candidates(qlaw, topk=3)
        if not candidates:
            continue
        if candidates and candidates[0].get("law_name") == "[조회오류]":
            errors.append(candidates[0].get("message", "법령 조회 오류"))
            continue
        # 정확 법령명 우선
        candidates.sort(key=lambda c: 0 if c.get("law_name") == qlaw else 1)
        for cand in candidates[:2]:
            data, err = get_law_detail(cand.get("mst", ""), cand.get("law_id", ""))
            if err:
                errors.append(f"{cand.get('law_name')}: {err}")
                continue
            articles = _extract_articles(data)
            scored = sorted(((_score_article(a, terms), a) for a in articles), key=lambda x: -x[0])
            picked = [a for s, a in scored if s > 0][:max(1, topk // 2)]
            for a in picked:
                results.append({
                    "law_name": cand.get("law_name", ""),
                    "article_no": a.get("article_no", ""),
                    "title": a.get("title", ""),
                    "content": a.get("content", "")[:1200],
                    "mst": cand.get("mst", ""),
                    "law_id": cand.get("law_id", ""),
                })
            if len(results) >= topk:
                return results[:topk]
    if not results and LAW_DEBUG and errors:
        return [{"law_name": "[조회오류]", "article_no": "", "title": "", "content": " / ".join(errors)[:1200]}]
    return results[:topk]


def _format_law(a: Dict[str, str], i: int) -> str:
    if a.get("law_name") == "[조회오류]":
        return f"{i}. [법제처 조회오류] {a.get('content', '')}"
    art = f"제{a.get('article_no')}조" if a.get("article_no") else "관련 조문"
    title = f"({a.get('title')})" if a.get("title") else ""
    return f"{i}. {a.get('law_name')} {art}{title}\n   {a.get('content', '')}"

# ──────────────────────────────────────────────────────────────
# 판단 보조
# ──────────────────────────────────────────────────────────────

def _domain(question: str) -> str:
    q = str(question)
    if any(k in q for k in ["재무", "회계", "예산", "결산", "추경", "전용", "관", "항", "목", "지출", "집행", "회식", "식대", "워크숍"]):
        return "재무회계"
    if any(k in q for k in ["근로계약", "고용보험", "4대보험", "사대보험", "육아휴직", "출산전후", "모성보호", "보조교사", "퇴사", "상실", "취득"]):
        return "인사노무"
    if any(k in q for k in ["놀이", "배움", "표준보육", "누리", "5개 영역", "흐름도"]):
        return "보육과정"
    if any(k in q for k in ["평가제", "평가", "평가지표"]):
        return "평가제"
    return "보육행정"


def _category_for_domain(domain: str, question: str) -> str:
    if domain == "재무회계":
        return "재무회계"
    if domain == "보육과정":
        if "0" in question or "1세" in question:
            return "0·1세 실행자료"
        if "2세" in question:
            return "2세 실행자료"
        if any(k in question for k in ["3세", "4세", "5세", "유아", "누리"]):
            return "누리과정"
        return "표준보육과정"
    if domain == "평가제":
        return "평가매뉴얼"
    if any(k in question for k in ["CCTV", "씨씨티비", "영상정보", "열람", "개인정보"]):
        return "보육사업안내 부록"
    return "보육사업안내"


def _guideline_strength(hits: List[Dict[str, Any]]) -> bool:
    if not hits:
        return False
    # 문서명과 실제 원문이 있으면 일단 근거로 인정. 쪽수 미표시는 약한 근거로 처리.
    return bool(hits[0].get("text"))


def _law_strength(laws: List[Dict[str, str]]) -> bool:
    if not laws:
        return False
    if laws[0].get("law_name") == "[조회오류]":
        return False
    return bool(laws[0].get("content"))


def _specific_interpretation(question: str, domain: str) -> Tuple[str, List[str], List[str], str]:
    """근거를 전제로 한 현장 해석 골격. 단정은 피하고 조건을 분리한다."""
    q = str(question)
    conclusion = "근거 확인 후 조건에 따라 판단해야 합니다."
    judgment: List[str] = []
    docs: List[str] = []
    risk = "근거 없이 임의 처리하면 민원·지도점검·회계 지적 또는 노동관계 분쟁으로 이어질 수 있습니다."

    if any(k in q for k in ["아침돌봄수당", "아침돌봄", "조기등원"]):
        conclusion = "‘아침돌봄수당’을 모든 어린이집이 무조건 지급해야 한다고 단정하면 안 됩니다."
        judgment = [
            "먼저 해당 수당이 지자체 보조사업 수당인지, 기관 내부수당인지, 실제 조기근무에 따른 임금인지 구분해야 합니다.",
            "실제 소정근로시간 밖에 조기근무를 명령·수행했다면 근로시간·임금 문제가 되므로 근로계약서, 근무표, 취업규칙 또는 내부수당기준을 함께 봐야 합니다.",
            "지자체 아침돌봄 지원사업으로 받은 예산이라면 해당 사업지침의 지급대상·단가·증빙 기준이 우선입니다.",
        ]
        docs = ["근무표 또는 출퇴근기록", "근로계약서", "수당 지급 기준", "지자체 사업지침", "내부결재 및 급여대장"]
    elif any(k in q for k in ["보조교사", "근로계약", "1년", "계약기간"]):
        conclusion = "보조교사 근로계약을 반드시 ‘1년 단위로만’ 해야 한다고 단정하면 안 됩니다."
        judgment = [
            "보조교사는 보육사업안내상 임면보고·지원사업 기준과 근로기준법상 근로조건 명시를 함께 봐야 합니다.",
            "계약기간은 사업기간, 예산지원기간, 실제 채용기간, 근무개시일, 회계연도 전환 시점을 함께 고려해야 합니다.",
            "1년 이상 계속근로가 예상되거나 갱신이 반복되면 퇴직급여·퇴직적립금·기간제 근로관계 리스크를 함께 검토해야 합니다.",
        ]
        docs = ["근로계약서", "임면보고 자료", "지원사업 선정·배정 자료", "근무표", "급여대장", "퇴직적립금 관련 자료"]
    elif any(k in q for k in ["CCTV", "씨씨티비", "열람", "영상정보"]):
        conclusion = "CCTV 열람은 원칙적으로 보호자 요청권을 전제로 검토하고, 거부는 제한 사유가 있을 때만 가능합니다."
        judgment = [
            "보관기간 경과로 영상이 파기된 경우인지 먼저 확인합니다.",
            "영유아의 이익, 사생활 침해, 다른 정보주체 보호 필요성을 이유로 제한하려면 운영위원회 등 판단 근거와 서면 통지가 필요합니다.",
            "단순히 다른 아이나 교직원이 나온다는 이유만으로 일괄 거부하기보다 열람 범위·시간·장소·보호조치를 조정해 검토해야 합니다.",
        ]
        docs = ["CCTV 열람요청서", "요청자 신분·보호자 확인자료", "열람통지서 또는 거부통지서", "운영위원회 검토자료", "영상정보 처리대장"]
    elif domain == "재무회계":
        conclusion = "지출 가능 여부는 먼저 지출 목적과 참석대상, 예산 편성 과목, 증빙 가능성을 기준으로 판단해야 합니다."
        judgment = [
            "관·항·목은 지출의 이름이 아니라 실제 목적과 성격으로 판단합니다.",
            "교직원 회식·워크숍 식대는 복리후생, 회의, 연수, 업무추진 성격 중 무엇인지 구분해야 합니다.",
            "예산에 없는 지출은 추경 또는 전용 가능 여부를 먼저 확인하고, 목적외 사용 금지 원칙을 반드시 봐야 합니다.",
        ]
        docs = ["사업계획 또는 내부결재", "참석자 명단", "회의·연수 자료", "카드전표·영수증", "지출결의서", "예산서·추경자료"]
    elif domain == "보육과정":
        conclusion = "놀이답변은 결과물이 아니라 영유아의 흥미·행동·관계·탐색과정을 5개 영역으로 읽어야 합니다."
        judgment = [
            "연령에 따라 0·1세, 2세, 3~5세 자료를 구분해 봅니다.",
            "신체운동·건강, 의사소통, 사회관계, 예술경험, 자연탐구 중 두드러진 배움과 통합적 배움을 함께 읽습니다.",
            "교사는 지시보다 관찰, 반응적 상호작용, 자료·공간·시간 지원으로 다음 놀이를 열어야 합니다.",
        ]
        docs = ["놀이관찰기록", "사진 또는 에피소드", "영유아 발화·몸짓 기록", "교사지원 기록", "다음 놀이 계획"]
    else:
        judgment = [
            "질문의 대상, 기간, 기관유형, 관계자, 비용 재원, 지자체 지침 여부를 먼저 구분합니다.",
            "법령 조문과 보육사업안내 문단이 같은 방향인지 확인합니다.",
            "예외 규정은 조건이 맞을 때만 적용합니다.",
        ]
        docs = ["요청서 또는 사실확인 기록", "관련 공문·안내문", "내부결재", "근거자료 출력본", "처리결과 기록"]
    return conclusion, judgment, docs, risk




def _needs_law(domain: str, question: str, law_name: str = "") -> bool:
    """질문 성격상 법령 조문 조회가 필요한지 판단한다.
    놀이·배움읽기·교육과정 질문에는 법령을 붙이지 않는다.
    """
    q = str(question)
    if law_name:
        return True
    if domain in {"보육과정", "평가제"}:
        return any(k in q for k in ["법", "법령", "조항", "의무", "처분", "위반", "설치근거", "법적"])
    if domain in {"재무회계", "인사노무"}:
        return True
    legal_keywords = [
        "CCTV", "씨씨티비", "영상정보", "열람", "거부", "운영위원회", "운영위", "인가", "설치", "정원",
        "배치기준", "임면", "채용", "결격", "보육료", "보육일수", "기관보육료", "지도점검", "시정명령",
        "행정처분", "민원", "개인정보", "아동학대", "감염병", "등원중지", "차량", "통학버스"
    ]
    return any(k in q for k in legal_keywords)


def _law_section_title(domain: str) -> str:
    if domain == "재무회계":
        return "재무·회계 규칙 근거"
    if domain == "인사노무":
        return "노동·고용보험 법령 근거"
    return "법령 근거"


def _guideline_section_title(domain: str) -> str:
    if domain == "보육과정":
        return "적용 자료"
    if domain == "재무회계":
        return "재무회계 매뉴얼·보육사업안내 근거"
    if domain == "평가제":
        return "평가매뉴얼 근거"
    if domain == "인사노무":
        return "보육교직원 관리·지원사업 근거"
    return "보육사업안내·공식자료 근거"


def _steps_for_domain(domain: str) -> List[str]:
    if domain == "보육과정":
        return [
            "놀이 장면에서 영유아가 실제로 한 말·몸짓·표정·관계를 먼저 적습니다.",
            "연령을 0·1세, 2세, 3~5세로 구분하고 해당 실행자료 또는 누리과정 자료를 적용합니다.",
            "5개 영역 중 억지로 모두 끼워 넣지 말고 실제 놀이에서 드러난 영역을 중심으로 배움읽기를 합니다.",
            "교사의 지원은 지시가 아니라 관찰, 반응적 상호작용, 자료·공간·시간 지원으로 제시합니다.",
            "다음 놀이는 오늘의 흥미가 이어질 수 있는 자료와 환경으로 계획합니다.",
        ]
    if domain == "재무회계":
        return [
            "지출명을 보지 말고 실제 목적, 참석대상, 활동 성격을 먼저 구분합니다.",
            "예산서에 편성된 관·항·목과 산출기초를 확인합니다.",
            "예산이 없거나 과목이 맞지 않으면 추경 또는 전용 가능 여부를 먼저 확인합니다.",
            "지출결의서, 카드전표, 영수증, 참석자 명단, 회의·연수 자료 등 증빙을 갖춥니다.",
            "목적외 사용, 사적 사용, 과다 집행 소지가 없는지 내부검토 기록을 남깁니다.",
        ]
    if domain == "인사노무":
        return [
            "대상자의 고용형태, 계약기간, 소정근로시간, 입사·퇴사·휴직일을 먼저 확인합니다.",
            "근로기준법·고용보험·4대보험 기준과 보육사업안내의 임면보고·지원사업 기준을 분리해 봅니다.",
            "근로계약서, 임면보고, 급여대장, 4대보험 신고자료가 서로 일치하는지 확인합니다.",
            "휴직·단축근무·대체인력 사안은 보육교직원 배치기준과 공백기간을 함께 검토합니다.",
            "변경사항은 교직원에게 서면으로 안내하고 기관 기록으로 보관합니다.",
        ]
    if domain == "평가제":
        return [
            "질문이 어느 평가영역과 평가지표에 해당하는지 먼저 분류합니다.",
            "관찰, 면담, 기록 중 어떤 방식으로 확인되는 항목인지 구분합니다.",
            "평가를 위한 형식적 문서보다 실제 운영과 일상기록이 연결되는지 확인합니다.",
            "부족한 부분은 지표별 보완자료와 현장 실행으로 정리합니다.",
        ]
    return [
        "사실관계와 대상자를 먼저 특정합니다.",
        "법령 조문이 필요한 사안인지, 지침만으로 충분한 사안인지 구분합니다.",
        "공식자료의 문서명·쪽수·문단을 확인합니다.",
        "허용, 제한, 예외, 추가확인 사항을 나누어 내부검토 기록으로 남깁니다.",
        "처리 후 안내내용, 근거자료, 관련 서류를 기관 문서로 보관합니다.",
    ]


def _format_domain_answer(domain: str, question: str, context: str, conclusion: str, judgment: List[str], docs: List[str], risk: str,
                          hits: List[Dict[str, Any]], laws: List[Dict[str, str]], include_law: bool) -> str:
    has_guideline = _guideline_strength(hits)
    has_law = _law_strength(laws) if include_law else False
    parts: List[str] = ["[보육나침반 현장답변]", f"질문: {question}", f"분류: {domain}"]
    if context:
        parts.append(f"추가상황: {context}")
    parts.append("")

    # 놀이·교육과정은 법령 답변 형식을 쓰지 않는다.
    if domain == "보육과정":
        if not has_guideline:
            parts.append("[결론]")
            parts.append("이 질문은 법령보다 표준보육과정·실행자료에 근거해 답해야 하는 사안입니다. 다만 현재 색인에서 해당 놀이와 직접 연결되는 자료 근거를 충분히 찾지 못했으므로, 연령과 놀이 장면을 더 구체화해 재조회해야 합니다.")
            parts.append("\n[필요한 놀이 정보]")
            parts.append("□ 연령 □ 놀이자료 □ 아이의 말·몸짓·표정 □ 또래관계 □ 교사의 개입 내용 □ 사진/관찰기록")
            return "\n".join(parts)
        parts.append("[배움읽기 결론]")
        parts.append(conclusion)
        parts.append(f"\n[{_guideline_section_title(domain)}]")
        for i, h in enumerate(hits[:5], 1):
            parts.append(_format_hit(h, i, limit=650))
        parts.append("\n[5개 영역 배움읽기]")
        for x in judgment:
            parts.append(f"- {x}")
        parts.append("\n[교사의 놀이지원]")
        for i, s in enumerate(_steps_for_domain(domain), 1):
            parts.append(f"{i}. {s}")
        parts.append("\n[기록에 남길 내용]")
        for d in docs:
            parts.append(f"□ {d}")
        parts.append("\n[주의]")
        parts.append("- 놀이흐름 답변에는 영유아보육법 조항을 억지로 붙이지 않습니다. 표준보육과정·실행자료·누리과정의 배움읽기와 교사지원이 중심입니다.")
        return "\n".join(parts)

    # 평가제도 평가매뉴얼 중심. 법령 질문일 때만 법령 표시.
    if domain == "평가제":
        if not has_guideline and not has_law:
            parts.append("[결론]")
            parts.append("평가제 질문은 평가매뉴얼의 영역·평가지표·확인방법을 기준으로 답해야 합니다. 현재 직접 근거 지표를 특정하지 못했으므로 지표명이나 상황을 더 구체화해야 합니다.")
            return "\n".join(parts)
        parts.append("[결론]")
        parts.append(conclusion)
        if include_law and has_law:
            parts.append(f"\n[{_law_section_title(domain)}]")
            for i, a in enumerate(laws[:3], 1):
                parts.append(_format_law(a, i))
        if has_guideline:
            parts.append(f"\n[{_guideline_section_title(domain)}]")
            for i, h in enumerate(hits[:5], 1):
                parts.append(_format_hit(h, i, limit=650))
        parts.append("\n[평가제 현장 점검]")
        for x in judgment:
            parts.append(f"- {x}")
        parts.append("\n[준비자료]")
        for d in docs:
            parts.append(f"□ {d}")
        return "\n".join(parts)

    # 재무/노무/행정은 질문 성격에 따라 법령 포함.
    if not has_guideline and not has_law:
        parts.append("[결론]")
        parts.append("현재 색인된 공식자료와 필요한 법령 조회 결과만으로는 이 사안을 단정할 근거를 특정하지 못했습니다. 이 상태에서 일반론으로 답하면 현장 판단을 오도할 수 있으므로, 질의를 더 구체화하거나 관련 지자체·관할청 안내를 함께 확인해야 합니다.")
        parts.append("\n[다시 물을 때 필요한 정보]")
        parts.append("□ 기관유형 □ 대상자 □ 발생일·기간 □ 비용 재원 □ 지자체 사업 여부 □ 근로계약·근무표 여부 □ 실제 요청 문서")
        return "\n".join(parts)

    parts.append("[결론]")
    parts.append(conclusion)

    parts.append("\n[적용 근거]")
    if include_law:
        if has_law:
            parts.append(f"■ {_law_section_title(domain)}")
            for i, a in enumerate(laws[:4], 1):
                parts.append(_format_law(a, i))
        else:
            parts.append(f"■ {_law_section_title(domain)}: 관련 조문을 특정하지 못했습니다. 법령명을 직접 지정해 재조회가 필요합니다.")
    else:
        parts.append("■ 법령 조문: 이 질문은 법령 조문보다 공식 지침·매뉴얼 적용이 우선인 사안으로 판단되어 법령을 억지로 붙이지 않습니다.")
    if has_guideline:
        parts.append(f"\n■ {_guideline_section_title(domain)}")
        for i, h in enumerate(hits[:5], 1):
            parts.append(_format_hit(h, i, limit=650))
    else:
        parts.append(f"\n■ {_guideline_section_title(domain)}: 직접 근거 문단을 찾지 못했습니다.")

    parts.append("\n[현장 판단]")
    for x in judgment:
        parts.append(f"- {x}")
    parts.append("- 위 근거가 질문의 사실관계와 맞는지 확인한 뒤 적용합니다. 근거와 다른 상황이면 단정하지 않습니다.")

    parts.append("\n[처리 절차]")
    for i, s in enumerate(_steps_for_domain(domain), 1):
        parts.append(f"{i}. {s}")

    parts.append("\n[남겨야 할 서류]")
    for d in docs:
        parts.append(f"□ {d}")
    parts.append("□ 적용 근거 출력본 또는 캡처")

    parts.append("\n[주의·리스크]")
    parts.append(f"- {risk}")
    parts.append("- 지자체 보조사업, 교육청·시군구 별도 지침, 근로계약 조건이 있으면 그 기준이 함께 적용될 수 있습니다.")

    parts.append("\n[현장 문안]")
    if domain == "재무회계":
        parts.append("해당 지출은 재무회계 매뉴얼의 관·항·목 기준과 증빙 가능 여부를 확인한 뒤 집행하겠습니다. 예산 편성 또는 과목이 맞지 않는 경우 추경·전용 가능 여부를 먼저 검토하겠습니다.")
    elif domain == "인사노무":
        parts.append("해당 사안은 근로계약, 보육교직원 임면보고, 4대보험·고용보험 신고 기준을 함께 확인하여 처리하겠습니다. 변경사항은 서면으로 정리해 안내드리겠습니다.")
    else:
        parts.append("해당 사안은 관련 법령과 보육사업안내 기준을 확인하여 처리하겠습니다. 확인된 근거에 따라 가능 여부와 절차를 안내드리고, 필요한 경우 서면으로 처리 사유와 근거를 남기겠습니다.")
    return "\n".join(parts)


def _build_answer(question: str, context: str = "", law_name: str = "", category_hint: str = "") -> str:
    full_q = " ".join([question, context]).strip()
    domain = _domain(full_q)
    cat = category_hint or _category_for_domain(domain, full_q)

    guideline_query = full_q
    if domain == "인사노무":
        guideline_query += " 보육교직원 임면 근로계약 보조교사 육아휴직 출산전후휴가"
    elif domain == "재무회계":
        guideline_query += " 재무회계 관 항 목 지출 예산 추경 전용 증빙 목적외 사용"
    elif domain == "보육과정":
        guideline_query += " 표준보육과정 5개 영역 배움 읽기 교사 지원 상호작용 공간 자료"
    elif domain == "평가제":
        guideline_query += " 평가매뉴얼 평가지표 관찰 면담 기록"

    hits = search_guidelines(guideline_query, topk=6, category_hint=cat)
    if len(hits) < 2:
        more = search_guidelines(guideline_query, topk=6, category_hint="")
        seen = {h.get("chunk_id") for h in hits}
        hits.extend([h for h in more if h.get("chunk_id") not in seen])
        hits = hits[:6]

    include_law = _needs_law(domain, full_q, law_name=law_name)
    laws = search_law_articles(full_q, law_name=law_name, topk=5) if include_law else []
    conclusion, judgment, docs, risk = _specific_interpretation(full_q, domain)
    return _format_domain_answer(domain, question, context, conclusion, judgment, docs, risk, hits, laws, include_law)
# ──────────────────────────────────────────────────────────────
# MCP Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
def get_legal_basis(질문: str, 법령명: str = "") -> str:
    """법제처 API로 관련 법령 조문을 먼저 찾습니다. 법령명·조문번호·조문제목·원문을 반환합니다."""
    laws = search_law_articles(질문, law_name=법령명, topk=6)
    parts = [f"[법령 조문 근거검색] {질문}"]
    if not laws:
        parts.append("관련 조문을 특정하지 못했습니다. 법령명을 직접 지정하거나 핵심어를 바꿔 다시 조회하세요.")
        parts.append("우선 조회 대상: " + ", ".join(_law_queries_for(질문, 법령명)))
        return "\n".join(parts)
    for i, a in enumerate(laws, 1):
        parts.append(_format_law(a, i))
    return "\n".join(parts)


@mcp.tool()
def get_guideline_basis(질문: str, 자료분류: str = "") -> str:
    """보육사업안내·부록·재무회계·평가매뉴얼·표준보육과정 색인에서 문서명·쪽수·원문 근거를 찾습니다."""
    hits = search_guidelines(질문, topk=8, category_hint=자료분류)
    parts = [f"[공식자료 근거검색] {질문}"]
    if not hits:
        parts.append("색인된 공식자료에서 직접 근거 문단을 찾지 못했습니다. 자료분류를 비우거나 핵심어를 바꿔 재조회하세요.")
        return "\n".join(parts)
    for i, h in enumerate(hits, 1):
        parts.append(_format_hit(h, i))
    return "\n".join(parts)


@mcp.tool()
def answer_childcare_case(질문: str, 기관유형: str = "", 대상자: str = "", 추가상황: str = "", 법령명: str = "", 자료분류: str = "") -> str:
    """최우선 현장답변 도구. 법령 조문과 공식자료 근거를 먼저 수집한 뒤, 결론·근거·판단·절차·서류·리스크 순서로 답합니다."""
    context = " ".join([기관유형, 대상자, 추가상황]).strip()
    return _build_answer(질문, context=context, law_name=법령명, category_hint=자료분류)


# 기존 PlayMCP 설정과 호환용 이름들
@mcp.tool()
def answer_childcare_admin_case(질문: str, 기관유형: str = "", 아동연령월령: str = "", 추가상황: str = "") -> str:
    """기존 호환용. 내부적으로 answer_childcare_case와 같은 엄격 근거형 답변을 반환합니다."""
    return answer_childcare_case(질문=질문, 기관유형=기관유형, 대상자=아동연령월령, 추가상황=추가상황)


@mcp.tool()
def search_childcare_basis(질의: str, 자료분류: str = "", 법령명: str = "") -> str:
    """질문 성격에 맞는 근거를 검색합니다. 놀이·평가제는 자료 중심, 법령 사안은 법령+지침으로 검색합니다."""
    domain = _domain(질의)
    include_law = _needs_law(domain, 질의, law_name=법령명)
    guideline = get_guideline_basis(질의, 자료분류=자료분류 or _category_for_domain(domain, 질의))
    if include_law:
        return get_legal_basis(질의, 법령명=법령명) + "\n\n" + guideline
    return guideline


@mcp.tool()
def search_law_only(질의: str, 법령명: str = "") -> str:
    """법제처 법령 조문 조회 전용."""
    return get_legal_basis(질의, 법령명=법령명)


@mcp.tool()
def search_law_and_guidelines(질의: str) -> str:
    """기존 호환용. 법령과 공식자료 근거를 함께 조회합니다."""
    return search_childcare_basis(질의)


@mcp.tool()
def check_employment_insurance_and_maternity(사안: str, 교직원상황: str = "", 확인할내용: str = "") -> str:
    """고용보험·4대보험·육아휴직·출산전후휴가·근로계약 사안을 보육사업안내와 노동관계 법령으로 함께 검토합니다."""
    q = " ".join([사안, 교직원상황, 확인할내용, "고용보험 4대보험 근로계약 육아휴직 출산전후휴가 모성보호"]).strip()
    return answer_childcare_case(질문=q, 자료분류="보육사업안내", 법령명="")


@mcp.tool()
def verify_accounting(지출내용: str, 계정과목: str = "", 추가상황: str = "") -> str:
    """어린이집 재무회계 관·항·목, 증빙, 추경·전용, 목적외 사용 여부를 검토합니다."""
    q = " ".join([지출내용, 계정과목, 추가상황, "재무회계 관 항 목 지출 증빙 추경 전용 목적외 사용"]).strip()
    return answer_childcare_case(질문=q, 자료분류="재무회계", 법령명="사회복지법인 및 사회복지시설 재무ㆍ회계 규칙")


@mcp.tool()
def map_play_to_curriculum(연령: str, 놀이상황: str, 관찰내용: str = "") -> str:
    """0·1세/2세/3~5세 놀이를 5개 영역, 배움읽기, 교사지원, 다음 놀이로 연결합니다."""
    q = " ".join([연령, 놀이상황, 관찰내용, "표준보육과정 5개 영역 배움 읽기 교사 지원 상호작용 공간 자료"]).strip()
    return answer_childcare_case(질문=q, 대상자=연령, 자료분류="표준보육과정")


@mcp.tool()
def make_childcare_admin_checklist(상황: str, 기관유형: str = "어린이집") -> str:
    """상황별 처리 체크리스트를 근거형 답변으로 생성합니다."""
    return answer_childcare_case(질문=상황, 기관유형=기관유형)


@mcp.tool()
def create_official_document(문서종류: str, 제목: str, 핵심내용: str, 어린이집명: str = "○○어린이집", 대상: str = "", 날짜: str = "") -> str:
    """공문·협조요청서·가정통신문·공지 초안을 작성합니다. 법적 판단은 answer_childcare_case로 먼저 확인하세요."""
    d = 날짜 or TODAY
    target = 대상 or "관계자"
    kind = str(문서종류).replace(" ", "")
    if kind in {"협조공문", "공문", "요청공문"}:
        return f"{어린이집명}\n\n수신: {target}\n제목: {제목}\n\n1. 귀 기관의 협조에 감사드립니다.\n2. {핵심내용}\n3. 관련 자료가 있는 경우 기한 내 회신하여 주시기 바랍니다.\n\n붙임: 해당 시 기재\n\n{d}\n{어린이집명} 원장 (직인)\n\n※ 법령·지침 근거가 필요한 사안은 answer_childcare_case로 근거 확인 후 문안을 확정하세요."
    if kind in {"가정통신문", "안내문", "공지"}:
        return f"[{제목}]\n\n안녕하세요. {어린이집명}입니다.\n\n{핵심내용}\n\n궁금하신 사항은 어린이집으로 문의해 주시기 바랍니다.\n\n{d}\n{어린이집명}\n\n※ 민원·권리·비용·안전 관련 사안은 answer_childcare_case로 근거 확인 후 발송하세요."
    return f"[{문서종류}] {제목}\n\n{핵심내용}\n\n일자: {d}\n기관: {어린이집명}\n대상: {target}"


@mcp.tool()
def review_admin_document(문서내용: str, 문서종류: str = "공지") -> str:
    """작성한 문서의 필수항목과 민원 소지 표현을 점검합니다."""
    text = str(문서내용)
    required = ["제목", "대상", "일자", "요청사항", "문의", "기관명"]
    found, missing = [], []
    for r in required:
        if r in text or (r == "일자" and re.search(r"\d{4}[.\-/년]|\d{1,2}\s*월", text)) or (r == "문의" and ("문의" in text or "연락" in text)):
            found.append(r)
        else:
            missing.append(r)
    risky = []
    replacements = {"무조건": "근거 확인 후", "절대": "원칙적으로", "안 됩니다": "제한될 수 있습니다", "책임지지 않습니다": "관련 기준에 따라 처리합니다"}
    for bad, good in replacements.items():
        if bad in text:
            risky.append(f"'{bad}' 표현은 '{good}'처럼 완화 권장")
    return "\n".join([
        f"[{문서종류} 문서점검]",
        f"포함된 항목: {', '.join(found) if found else '확인 어려움'}",
        f"보완할 항목: {', '.join(missing) if missing else '대체로 포함'}",
        "표현 점검: " + (" / ".join(risky) if risky else "큰 민원 소지 표현은 확인되지 않았습니다."),
        "권리·비용·안전·CCTV·회계·노무 사안은 발송 전 answer_childcare_case로 법령·지침 근거를 확인하세요.",
    ])


@mcp.tool()
def check_index_status() -> str:
    """현재 공식자료 색인과 법제처 환경변수 상태를 점검합니다."""
    docs: Dict[str, int] = {}
    cats: Dict[str, int] = {}
    for c in GUIDELINE_INDEX:
        docs[c.get("doc_title", "공식자료")] = docs.get(c.get("doc_title", "공식자료"), 0) + 1
        cats[c.get("category", "기타")] = cats.get(c.get("category", "기타"), 0) + 1
    parts = ["[보육나침반 색인 상태]"]
    parts.append(f"총 색인 조각 수: {len(GUIDELINE_INDEX)}")
    parts.append(f"법제처 OC 설정: {'있음' if LAW_OC else '없음'}")
    parts.append(f"LAW_DEBUG: {LAW_DEBUG}")
    parts.append("\n[문서별 조각 수]")
    if docs:
        for name, count in sorted(docs.items(), key=lambda x: -x[1])[:40]:
            parts.append(f"- {name}: {count}개")
    else:
        parts.append("- 색인 파일을 찾지 못했습니다. data/index/childcare_chunks.jsonl을 배치하세요.")
    parts.append("\n[필수 자료 체크]")
    hay = " ".join(docs.keys())
    for req in REQUIRED_DOCS:
        ok = any(tok in hay for tok in _tokenize(req))
        parts.append(f"{'✅' if ok else '⚠️'} {req}")
    return "\n".join(parts)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
