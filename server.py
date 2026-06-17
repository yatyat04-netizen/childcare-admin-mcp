# -*- coding: utf-8 -*-
"""
어린이집사 — 보육행정 에이전트 MCP 서버 (Agentic Player 10 출품)
====================================================================
어린이집 원장·행정 담당을 위한 '실무를 아는' 행정 에이전트.

핵심 원칙: 자연스러운 문장 생성은 호스트 AI(카카오)가 하고,
이 서버는 'AI가 혼자 못 하는 것'을 쥐여준다.
  - 실제 지침서(보육사업안내·재무회계 등)에서 근거를 찾아옴 (서버 내장, 항상 즉답)
  - 영유아보육법 등 법령은 법제처 API로 조회 (best-effort)
  - 어린이집 서식·절차·놀이흐름도 프레임 제공

도구 5개:
  1. search_law_and_guidelines  — 지침·법령에서 근거 즉답  ★핵심
  2. create_official_document   — 공문/가정통신문/회의록 초안
  3. review_admin_document      — 작성한 문서 검토
  4. guide_admin_procedure      — 행정 절차+서류+근거 안내
  5. create_play_flow           — 놀이흐름도 설계
"""

import os
import re
import json
from datetime import date

from mcp.server.fastmcp import FastMCP

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))

# 배포 환경에서 외부 접속 가능하도록 0.0.0.0 바인딩
mcp = FastMCP("childcare-admin", host="0.0.0.0", port=PORT)

오늘 = date.today().isoformat()

# ──────────────────────────────────────────────────────────────
# 지침 검색 엔진 (서버 내장 — 인터넷 없어도 항상 동작)
# ──────────────────────────────────────────────────────────────
try:
    with open(os.path.join(HERE, "guideline_index.json"), encoding="utf-8") as f:
        GUIDELINE_INDEX = json.load(f)
except Exception:
    GUIDELINE_INDEX = []


def _tokenize(s: str):
    return [t for t in re.findall(r"[가-힣A-Za-z0-9]+", s) if len(t) >= 2]


def _search_guidelines(query: str, topk: int = 3):
    """내장 지침서에서 질의와 관련된 조각을 점수순으로 찾아 반환."""
    qts = _tokenize(query)
    if not qts or not GUIDELINE_INDEX:
        return []
    scored = []
    for item in GUIDELINE_INDEX:
        txt = item.get("text", "")
        score = sum(txt.count(t) for t in qts)
        if all(t in txt for t in qts):
            score += 5
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, item in scored[:topk]:
        snippet = re.sub(r"\s+", " ", item.get("text", "")).strip()
        out.append({"source": item.get("source", "지침서"), "text": snippet[:500]})
    return out


# ──────────────────────────────────────────────────────────────
# 법령 조회 (법제처 OPEN API — best-effort, 실패해도 서버는 안전)
# ──────────────────────────────────────────────────────────────
LAW_OC = os.environ.get("LAW_GO_KR_OC", "yatyat4542")


def _fetch_law_names(query: str, topk: int = 3):
    """법제처 API로 관련 법령명을 best-effort 조회. 실패 시 빈 리스트."""
    try:
        import httpx

        url = "https://www.law.go.kr/DRF/lawSearch.do"
        params = {"OC": LAW_OC, "target": "law", "query": query, "type": "JSON"}
        r = httpx.get(url, params=params, timeout=6.0)
        data = r.json()
        # 응답 구조가 버전마다 달라서 방어적으로 탐색
        laws = []

        def walk(obj):
            if isinstance(obj, dict):
                name = obj.get("법령명한글") or obj.get("법령명")
                if name:
                    laws.append(str(name).strip())
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(data)
        # 중복 제거, 상위 N
        seen, uniq = set(), []
        for n in laws:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        return uniq[:topk]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────
# Tool 1. 지침·법령 근거 조회  ★핵심
# ──────────────────────────────────────────────────────────────
@mcp.tool()
def search_law_and_guidelines(질의: str) -> str:
    """어린이집 행정 질문에 대해 실제 지침서·법령에서 근거를 찾아 즉시 답합니다.

    [트리거] "근거", "법령", "조항", "지침", "보육사업안내", "재무회계",
            "운영위원회", "교사 비율", "예산", "보조금", "이거 맞아?", "어떻게 해야 해?"
    [용도] AI의 추측이 아니라 실제 지침서(2026 보육사업안내·부록, 2025 재무회계
          매뉴얼) 원문과 관련 법령명을 근거로 제공합니다. 호스트 AI는 이 근거를
          바탕으로 깔끔한 해결책을 작성하세요. 근거 출처를 반드시 함께 안내하세요.

    Args:
        질의: 알고 싶은 내용 (예: "운영위원회 구성", "예산 편성 절차", "교사 대 아동 비율")
    """
    parts = []
    hits = _search_guidelines(질의, topk=3)
    if hits:
        parts.append("[지침서 근거]")
        for h in hits:
            parts.append(f"\n▷ 출처: {h['source']}\n{h['text']}")
    else:
        parts.append("[지침서] 관련 내용을 찾지 못했어요. 질문을 조금 더 구체적으로 적어보세요.")

    law_names = _fetch_law_names(질의, topk=3)
    if law_names:
        parts.append("\n\n[관련 법령 (법제처)]")
        for n in law_names:
            parts.append(f"- {n}")
        parts.append("(법령 원문은 법제처 국가법령정보센터 기준)")

    parts.append(
        "\n\n※ 호스트 AI 안내: 위 근거를 바탕으로 사용자에게 단계별 해결책을 제시하고, "
        "출처(지침서명/법령명)를 함께 표기하세요. 근거에 없는 내용은 단정하지 마세요."
    )
    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────
# Tool 2. 공식문서 작성
# ──────────────────────────────────────────────────────────────
@mcp.tool()
def create_official_document(
    문서종류: str,
    제목: str,
    핵심내용: str,
    어린이집명: str = "○○어린이집",
    원장명: str = "○○○",
    대상: str = "",
    날짜: str = "",
) -> str:
    """어린이집 공식문서(공문)의 서식 구조에 맞춘 초안을 생성합니다.

    [트리거] "가정통신문", "공지", "공문", "회의록", "인계인수서",
            "안내문 써줘", "공문 만들어줘", "문서 작성"
    [용도] 어린이집 행정 문서의 정확한 서식 골격에 핵심내용을 채워 초안을 돌려줍니다.
          호스트 AI가 이 골격을 따뜻하고 신뢰감 있는 문체로 다듬으세요.

    Args:
        문서종류: 가정통신문 | 공지사항 | 운영위원회회의록 | 직원회의록 | 협조공문 | 사무인계인수서
        제목: 문서 제목/주제
        핵심내용: 전달할 핵심 내용
        어린이집명: 발신 기관명
        원장명: 발신자(원장) 성명
        대상: 수신 대상
        날짜: 문서 일자 (미입력 시 오늘)
    """
    d = 날짜 or 오늘
    종류 = 문서종류.replace(" ", "")

    if 종류 in ("가정통신문", "안내문"):
        대상 = 대상 or "학부모님"
        return (f"[가정통신문]  {제목}\n\n{어린이집명}\n\n존경하는 {대상}께,\n\n{핵심내용}\n\n"
                f"위 내용을 안내드리오니 협조 부탁드립니다.\n문의사항은 언제든지 원으로 연락 주시기 바랍니다.\n\n"
                f"{d}\n{어린이집명} 원장 {원장명}\n\n"
                f"※ 작성가이드: ①인사말 ②안내배경 ③구체일정·준비물 ④협조요청 ⑤문의처 포함. 따뜻한 문체로 다듬을 것.")
    if 종류 in ("공지사항", "공지"):
        대상 = 대상 or "교직원"
        return f"[공지]  {제목}\n\n수신: {대상}\n일자: {d}\n\n{핵심내용}\n\n위와 같이 공지하오니 숙지하여 주시기 바랍니다.\n\n{어린이집명}"
    if 종류 in ("운영위원회회의록", "운영위원회"):
        return (f"[{어린이집명} 운영위원회 회의록]\n\n1. 일시: {d}\n2. 장소:\n"
                f"3. 참석: (위원 ○명 중 ○명 — 보호자위원/교직원위원/지역위원)\n4. 안건:\n   {핵심내용}\n"
                f"5. 논의 및 결정사항:\n   가.\n   나.\n6. 기타:\n7. 차기 회의:\n\n작성자:            확인(원장): {원장명}\n\n"
                f"※ 운영위 구성·정족수·개최주기는 search_law_and_guidelines로 근거 확인 후 함께 안내.")
    if 종류 in ("직원회의록", "직원회의"):
        return (f"[{어린이집명} 직원회의록]\n\n1. 일시: {d}\n2. 참석:\n3. 안건:\n   {핵심내용}\n"
                f"4. 협의내용:\n5. 결정 및 업무분장:\n6. 전달사항:\n\n작성자:            결재(원장): {원장명}")
    if 종류 in ("협조공문", "공문"):
        대상 = 대상 or "관계기관"
        return (f"{어린이집명}\n\n수신: {대상}\n제목: {제목}\n\n1. 귀 기관의 무궁한 발전을 기원합니다.\n"
                f"2. {핵심내용}\n3. 협조하여 주시기 바랍니다.\n\n붙임:  1.\n\n{d}\n{어린이집명} 원장 {원장명}  (직인)")
    if 종류 in ("사무인계인수서",):
        return (f"[사무인계인수서]\n\n1. 인계자:                    2. 인수자:\n3. 인계인수 일자: {d}\n"
                f"4. 직위/담당업무:\n5. 인계인수 내역:\n   {핵심내용}\n   - 진행 중 업무:\n   - 보관 문서·물품:\n   - 인장·통장·열쇠 등:\n"
                f"6. 특이사항:\n\n인계자(서명):            인수자(서명):\n입회/원장 {원장명}(서명):")
    return (f"'{문서종류}'는 등록된 서식이 없어요. 지원: 가정통신문/공지사항/운영위원회회의록/"
            f"직원회의록/협조공문/사무인계인수서.")


# ──────────────────────────────────────────────────────────────
# Tool 3. 공식문서 검토
# ──────────────────────────────────────────────────────────────
필수항목 = {
    "가정통신문": ["제목", "인사말", "안내 배경/목적", "구체 일정·날짜", "준비물/협조사항", "문의처", "발신일자", "어린이집명·원장명"],
    "운영위원회회의록": ["일시", "장소", "참석자(정족수)", "안건", "논의·결정사항", "작성자/확인자"],
    "직원회의록": ["일시", "참석자", "안건", "협의내용", "결정·업무분장", "전달사항"],
    "협조공문": ["수신처", "제목", "본문(요청사항)", "붙임", "발신일자", "기관명·직인"],
}


@mcp.tool()
def review_admin_document(문서내용: str, 문서종류: str = "가정통신문") -> str:
    """작성한 어린이집 문서를 검토해 빠진 필수 항목과 보완점을 알려줍니다.

    [트리거] "검토", "확인해줘", "빠진 거 없어?", "이거 괜찮아?", "점검"
    [용도] 사용자가 쓴 문서에 어린이집 서식상 필수 항목이 빠지지 않았는지 점검합니다.
          호스트 AI는 결과를 친절하게 정리해 안내하세요.

    Args:
        문서내용: 검토할 문서 전문
        문서종류: 가정통신문 | 운영위원회회의록 | 직원회의록 | 협조공문
    """
    종류 = 문서종류.replace(" ", "")
    items = 필수항목.get(종류)
    if not items:
        return (f"'{문서종류}' 검토 기준이 아직 없어요. 지원: " + " / ".join(필수항목.keys()))
    found, missing = [], []
    text = 문서내용
    # 아주 단순한 휴리스틱 체크 (키워드/날짜 패턴)
    checks = {
        "발신일자": bool(re.search(r"\d{4}[.\-/년]", text)),
        "구체 일정·날짜": bool(re.search(r"\d{1,2}\s*월|\d{1,2}\s*일|\d{4}[.\-/]", text)),
        "문의처": ("문의" in text or "연락" in text),
        "인사말": ("안녕" in text or "존경" in text or "사랑" in text),
    }
    for it in items:
        ok = checks.get(it)
        if ok is None:
            ok = any(k in text for k in re.findall(r"[가-힣]+", it))
        (found if ok else missing).append(it)
    res = [f"[{문서종류} 검토 결과]", f"\n✅ 포함됨: {', '.join(found) if found else '없음'}",
           f"\n⚠️ 빠졌을 수 있음: {', '.join(missing) if missing else '없음 (필수 항목 모두 포함)'}"]
    res.append("\n\n※ 호스트 AI: 빠진 항목을 사용자에게 친절히 짚어주고, 어떻게 보완하면 좋을지 제안하세요.")
    return "\n".join(res)


# ──────────────────────────────────────────────────────────────
# Tool 4. 행정 절차 안내
# ──────────────────────────────────────────────────────────────
절차_DB = {
    "운영위원회 구성": {
        "단계": ["위원 구성(보호자·교직원·지역위원)", "위원 위촉 및 명단 정리",
                "정기회의 개최(분기별 1회 이상 권장)", "회의록 작성·보관 및 결과 안내"],
        "서류": ["위원 명단", "위촉 문서", "회의록"],
        "근거확인": "운영위 구성·정족수·주기는 search_law_and_guidelines로 보육사업안내 최신본 확인",
    },
    "신규 교사 채용": {
        "단계": ["채용 공고·접수", "자격(보육교사 자격증) 확인", "면접·선발",
                "결격사유 확인(건강진단·성범죄경력·아동학대 조회)", "근로계약·4대보험 신고",
                "보육통합정보시스템 인력 등록"],
        "서류": ["자격증 사본", "건강진단 결과", "범죄경력 조회 동의/결과", "근로계약서"],
        "근거확인": "결격사유 조회는 채용 전 필수. 최신 절차는 search_law_and_guidelines로 확인",
    },
}


@mcp.tool()
def guide_admin_procedure(업무: str) -> str:
    """어린이집 행정 업무의 '절차 + 필요서류 + 근거확인 방법'을 단계별로 안내합니다.

    [트리거] "절차", "어떻게 해야 해", "뭐부터", "필요한 서류", "채용 절차", "운영위 어떻게"
    [용도] 단순 문서 생성이 아니라 무엇을 어떤 순서로 해야 하는지 알려주는 핵심 기능.

    Args:
        업무: 안내받을 업무명 (예: "신규 교사 채용", "운영위원회 구성")
    """
    매칭 = None
    for key in 절차_DB:
        if key in 업무 or 업무 in key or any(w in 업무 for w in key.split()):
            매칭 = key
            break
    if not 매칭:
        return (f"'{업무}' 절차는 아직 등록 전이에요. 현재 등록: " + " / ".join(절차_DB.keys())
                + "\n(다른 업무는 search_law_and_guidelines로 지침에서 근거를 찾아볼 수 있어요.)")
    p = 절차_DB[매칭]
    단계 = "\n".join(f"  {i}. {s}" for i, s in enumerate(p["단계"], 1))
    return (f"[{매칭} — 행정 절차]\n\n▷ 진행 단계\n{단계}\n\n▷ 필요 서류: {', '.join(p['서류'])}\n"
            f"▷ 근거 확인: {p['근거확인']}")


# ──────────────────────────────────────────────────────────────
# Tool 5. 놀이흐름도 설계
# ──────────────────────────────────────────────────────────────
@mcp.tool()
def create_play_flow(놀이주제: str, 연령: str = "만 2세", 자료: str = "", 중심영역: str = "") -> str:
    """놀이중심·비구조화 놀이 기반의 '놀이흐름도' 설계 골격을 생성합니다.

    [트리거] "놀이흐름도", "놀이 설계", "놀이안", "흐름도 짜줘", "loose parts", "놀이 계획"
    [용도] 도입-전개-확장-마무리 흐름에 교사 역할·발문·관찰포인트를 짜주는 설계 프레임.

    Args:
        놀이주제: 주제/소재 (예: "가을 낙엽")
        연령: 대상 연령 (예: "만 2세")
        자료: 사용할 자료/Loose Parts
        중심영역: 강조할 발달/경험 영역
    """
    자료줄 = f"제공 자료: {자료}\n" if 자료 else "제공 자료: (열린 자료 / Loose Parts 자유 선택)\n"
    영역줄 = f"중심 영역: {중심영역}\n" if 중심영역 else ""
    return (f"[놀이흐름도]  주제: {놀이주제}  /  대상: {연령}\n{자료줄}{영역줄}\n"
            f"① 도입(놀이 열기) — 교사: 흥미 유발, 자료 자연스레 배치 / 발문: \"이걸로 뭘 해볼까?\" / 관찰: 먼저 다가가는 자료\n"
            f"② 전개(놀이 펼치기) — 교사: 개입 최소화, 아이 주도 따라가기 / 발문: \"어떻게 그렇게 됐어?\" / 관찰: 자료 변형·또래 상호작용\n"
            f"③ 확장(깊이 더하기) — 교사: 새 자료·공간 제안 / 관찰: 놀이가 뻗어가는 방향\n"
            f"④ 마무리(놀이 나누기) — 교사: 경험 공유, 흔적 함께 보기 / 관찰: 의미 있게 기억하는 순간\n\n"
            f"※ 비구조화 놀이 원칙: '정답 흐름'이 아니라 '가능성의 지도'. 호스트 AI는 {연령} 발달과 "
            f"{놀이주제}에 맞춰 구체화하고, 표준보육과정 연계는 search_law_and_guidelines로 보강.")


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
