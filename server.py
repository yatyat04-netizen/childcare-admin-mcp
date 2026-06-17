# -*- coding: utf-8 -*-
"""
어린이집사 — 보육행정 검증 에이전트 MCP 서버 (Agentic Player 10 출품)
====================================================================
"AI는 행정을 수행하고, 인간은 판단하며, 시간은 아이에게 돌아간다."

분산된 보육행정을 AI가 수행·검증하고, 사람은 판단에 집중하도록 돕는다.
모든 응답은 실제 지침서·법령 '근거'에 기반한다. (서버 내장 지침 + 법제처 법령 API)

설계 원칙:
  - 자연스러운 문장 생성은 호스트 AI가 한다.
  - 이 서버는 정확한 근거(지침 원문·법령), 서식, 절차, 검증 프레임을 제공한다.
  - 어떤 입력에도 절대 예외(오류)로 죽지 않는다. 모든 도구는 항상 문자열을 반환한다.

내장 자료(검색): 2026 보육사업안내(본문/부록), 2025 재무회계 매뉴얼,
  2024 개정 표준보육과정(해설서/0-1세/2세 실행자료), 2019 개정 누리과정 놀이실행자료.
"""

import os
import re
import json
from datetime import date

from mcp.server.fastmcp import FastMCP

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))

mcp = FastMCP("childcare-admin", host="0.0.0.0", port=PORT)

try:
    오늘 = date.today().isoformat()
except Exception:
    오늘 = ""

# ──────────────────────────────────────────────────────────────
# 지침 검색 엔진 (서버 내장 — 항상 동작)
# ──────────────────────────────────────────────────────────────
try:
    with open(os.path.join(HERE, "guideline_index.json"), encoding="utf-8") as _f:
        GUIDELINE_INDEX = json.load(_f)
    if not isinstance(GUIDELINE_INDEX, list):
        GUIDELINE_INDEX = []
except Exception:
    GUIDELINE_INDEX = []


def _tokenize(s):
    try:
        return [t for t in re.findall(r"[가-힣A-Za-z0-9]+", str(s)) if len(t) >= 2]
    except Exception:
        return []


def _search_guidelines(query, topk=3, source_keyword=""):
    """내장 지침서에서 질의 관련 조각을 점수순으로 반환. 절대 예외 없음."""
    try:
        qts = _tokenize(query)
        if not qts or not GUIDELINE_INDEX:
            return []
        scored = []
        for item in GUIDELINE_INDEX:
            try:
                txt = item.get("text", "")
                src = item.get("source", "")
                if source_keyword and source_keyword not in src:
                    continue
                score = sum(txt.count(t) for t in qts)
                if all(t in txt for t in qts):
                    score += 5
                if score > 0:
                    scored.append((score, item))
            except Exception:
                continue
        scored.sort(key=lambda x: -x[0])
        out = []
        for _score, item in scored[:topk]:
            snippet = re.sub(r"\s+", " ", item.get("text", "")).strip()
            out.append({"source": item.get("source", "지침서"), "text": snippet[:500]})
        return out
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────
# 법제처 법령 API (best-effort, 실패해도 절대 안 죽음)
# ──────────────────────────────────────────────────────────────
LAW_OC = os.environ.get("LAW_GO_KR_OC", "yatyat4542")


def _fetch_law_names(query, topk=4):
    """법제처 OPEN API로 관련 법령명 조회. 어떤 경우에도 리스트 반환(예외 없음)."""
    try:
        import httpx

        url = "https://www.law.go.kr/DRF/lawSearch.do"
        params = {"OC": LAW_OC, "target": "law", "query": str(query), "type": "JSON"}
        r = httpx.get(url, params=params, timeout=6.0)
        if r.status_code != 200:
            return []
        data = r.json()
        names = []

        def walk(obj):
            try:
                if isinstance(obj, dict):
                    nm = obj.get("법령명한글") or obj.get("법령명")
                    if nm:
                        names.append(str(nm).strip())
                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    for v in obj:
                        walk(v)
            except Exception:
                return

        walk(data)
        seen, uniq = set(), []
        for n in names:
            if n and n not in seen:
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
    """어린이집 행정 질문에 실제 지침서·법령에서 근거를 찾아 즉시 답합니다.

    [트리거] "근거", "법령", "법", "조항", "지침", "보육사업안내", "재무회계",
            "표준보육과정", "누리과정", "운영위원회", "교사 비율", "예산", "보조금",
            "이거 맞아?", "어떻게 해야 해?", "규정"
    [용도] AI 추측이 아니라 실제 지침서 원문(보육사업안내·재무회계 매뉴얼·표준보육과정·
          누리과정)과 법제처 관련 법령명을 근거로 제공합니다. 호스트 AI는 이 근거로
          해결책을 작성하고 출처(지침서명/법령명)를 반드시 함께 안내하세요. 근거에 없는
          내용은 단정하지 마세요.

    Args:
        질의: 알고 싶은 내용 (예: "운영위원회 구성", "예산 편성 절차", "표준보육과정 5개 영역")
    """
    try:
        parts = []
        hits = _search_guidelines(질의, topk=3)
        if hits:
            parts.append("[지침서 근거]")
            for h in hits:
                parts.append("\n▷ 출처: " + h["source"] + "\n" + h["text"])
        else:
            parts.append("[지침서] 관련 내용을 못 찾았어요. 키워드를 조금 더 구체적으로 적어보세요.")

        law_names = _fetch_law_names(질의)
        if law_names:
            parts.append("\n\n[관련 법령 (법제처 국가법령정보)]")
            for n in law_names:
                parts.append("- " + n)
            parts.append("(법령 원문 출처: 법제처)")

        parts.append(
            "\n\n※ 호스트 AI: 위 근거로 단계별 해결책을 제시하고 출처를 함께 표기하세요. "
            "근거에 없는 내용은 단정하지 말고 확인 방법을 안내하세요."
        )
        return "\n".join(parts)
    except Exception:
        return "조회 중 일시적 문제가 있었어요. 질의를 조금 바꿔 다시 시도해 주세요."


# ──────────────────────────────────────────────────────────────
# Tool 2. 회계 집행 검증  ★검증 중심 핵심
# ──────────────────────────────────────────────────────────────
@mcp.tool()
def verify_accounting(지출내용: str, 계정과목: str = "", 비고: str = "") -> str:
    """어린이집 회계 집행의 적정성을 재무회계 매뉴얼 근거로 검증하도록 돕습니다.

    [트리거] "회계 검증", "이 계정 맞아?", "계정과목", "집행", "집행률", "예산 위반",
            "행정처분", "이 비용 처리", "목적외 사용"
    [용도] 어떤 지출을 어떤 계정과목에 집행하는 게 맞는지, 집행률이 적정한지, 위반/행정처분
          사항인지 판단할 근거(재무회계 규정)와 검증 체크리스트를 제공합니다. 호스트 AI는
          이를 바탕으로 '적정 / 부적정 / 추가확인 필요'를 판단해 안내하세요.

    Args:
        지출내용: 검증할 지출/물품 (예: "교사 워크숍 식대", "교재교구 구입")
        계정과목: 집행하려는(또는 집행한) 계정과목 (예: "운영비", "교재교구비")
        비고: 추가 상황 (예: "예산 80% 집행 상태")
    """
    try:
        q = " ".join([x for x in [지출내용, 계정과목, 비고] if x]).strip() or 지출내용
        hits = _search_guidelines(q, topk=3, source_keyword="재무회계")
        if not hits:
            hits = _search_guidelines(q, topk=2)
        head = "[회계 집행 검증]  지출: " + str(지출내용)
        if 계정과목:
            head += "  /  계정과목(안): " + str(계정과목)
        parts = [head]
        if hits:
            parts.append("\n[관련 재무회계 규정 근거]")
            for h in hits:
                parts.append("\n▷ 출처: " + h["source"] + "\n" + h["text"])
        else:
            parts.append("\n관련 규정을 못 찾았어요. 지출내용/계정과목을 더 구체적으로 적어보세요.")
        parts.append(
            "\n\n[검증 포인트 — 호스트 AI가 위 근거로 판단]\n"
            "1. 계정과목 적정성: 이 지출이 해당 계정과목 정의에 맞는지 대조\n"
            "2. 집행률: 예산 대비 집행률이 적정한지(과다·과소·목적외 여부)\n"
            "3. 위반·행정처분: 목적외 사용·부적정 집행이면 영유아보육법·사회복지시설 재무회계규칙상 "
            "시정명령·반환·행정처분 대상일 수 있음 → search_law_and_guidelines로 근거 확인\n"
            "※ 단정이 어려우면 '추가확인 필요'로 안내하고 확인 방법을 함께 제시하세요."
        )
        return "\n".join(parts)
    except Exception:
        return "검증 중 일시적 문제가 있었어요. 지출내용을 조금 바꿔 다시 시도해 주세요."


# ──────────────────────────────────────────────────────────────
# Tool 3. 공식문서 작성
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

    [트리거] "가정통신문", "공지", "공문", "회의록", "인계인수서", "안내문 써줘", "문서 작성"
    [용도] 정확한 서식 골격에 핵심내용을 채워 초안을 돌려줍니다. 호스트 AI가 따뜻하고
          신뢰감 있는 문체로 다듬으세요.

    Args:
        문서종류: 가정통신문 | 공지사항 | 운영위원회회의록 | 직원회의록 | 협조공문 | 사무인계인수서
        제목: 문서 제목/주제
        핵심내용: 전달할 핵심 내용
        어린이집명: 발신 기관명
        원장명: 발신자(원장) 성명
        대상: 수신 대상
        날짜: 문서 일자 (미입력 시 오늘)
    """
    try:
        d = 날짜 or 오늘
        종류 = str(문서종류).replace(" ", "")
        if 종류 in ("가정통신문", "안내문"):
            대상 = 대상 or "학부모님"
            return ("[가정통신문]  " + str(제목) + "\n\n" + str(어린이집명) + "\n\n존경하는 " + 대상 + "께,\n\n"
                    + str(핵심내용) + "\n\n위 내용을 안내드리오니 협조 부탁드립니다.\n"
                    "문의사항은 언제든지 원으로 연락 주시기 바랍니다.\n\n" + d + "\n" + str(어린이집명) + " 원장 " + str(원장명)
                    + "\n\n※ 작성가이드: ①인사말 ②안내배경 ③구체일정·준비물 ④협조요청 ⑤문의처. 따뜻한 문체로 다듬을 것.")
        if 종류 in ("공지사항", "공지"):
            대상 = 대상 or "교직원"
            return ("[공지]  " + str(제목) + "\n\n수신: " + 대상 + "\n일자: " + d + "\n\n" + str(핵심내용)
                    + "\n\n위와 같이 공지하오니 숙지하여 주시기 바랍니다.\n\n" + str(어린이집명))
        if 종류 in ("운영위원회회의록", "운영위원회"):
            return ("[" + str(어린이집명) + " 운영위원회 회의록]\n\n1. 일시: " + d + "\n2. 장소:\n"
                    "3. 참석: (위원 ○명 중 ○명 — 보호자위원/교직원위원/지역위원)\n4. 안건:\n   " + str(핵심내용)
                    + "\n5. 논의 및 결정사항:\n   가.\n   나.\n6. 기타:\n7. 차기 회의:\n\n작성자:            확인(원장): "
                    + str(원장명) + "\n\n※ 운영위 구성·정족수·주기는 search_law_and_guidelines로 근거 확인 후 안내.")
        if 종류 in ("직원회의록", "직원회의"):
            return ("[" + str(어린이집명) + " 직원회의록]\n\n1. 일시: " + d + "\n2. 참석:\n3. 안건:\n   "
                    + str(핵심내용) + "\n4. 협의내용:\n5. 결정 및 업무분장:\n6. 전달사항:\n\n작성자:            결재(원장): "
                    + str(원장명))
        if 종류 in ("협조공문", "공문"):
            대상 = 대상 or "관계기관"
            return (str(어린이집명) + "\n\n수신: " + 대상 + "\n제목: " + str(제목)
                    + "\n\n1. 귀 기관의 무궁한 발전을 기원합니다.\n2. " + str(핵심내용)
                    + "\n3. 협조하여 주시기 바랍니다.\n\n붙임:  1.\n\n" + d + "\n" + str(어린이집명) + " 원장 " + str(원장명) + "  (직인)")
        if 종류 == "사무인계인수서":
            return ("[사무인계인수서]\n\n1. 인계자:                    2. 인수자:\n3. 인계인수 일자: " + d
                    + "\n4. 직위/담당업무:\n5. 인계인수 내역:\n   " + str(핵심내용)
                    + "\n   - 진행 중 업무:\n   - 보관 문서·물품:\n   - 인장·통장·열쇠 등:\n6. 특이사항:\n\n"
                    "인계자(서명):            인수자(서명):\n입회/원장 " + str(원장명) + "(서명):")
        return ("'" + str(문서종류) + "'는 등록된 서식이 없어요. 지원: 가정통신문/공지사항/운영위원회회의록/"
                "직원회의록/협조공문/사무인계인수서.")
    except Exception:
        return "문서 생성 중 일시적 문제가 있었어요. 입력을 확인해 다시 시도해 주세요."


# ──────────────────────────────────────────────────────────────
# Tool 4. 공식문서 검토
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
    [용도] 문서에 서식상 필수 항목이 빠지지 않았는지 점검합니다. 호스트 AI는 결과를
          친절하게 정리해 안내하세요.

    Args:
        문서내용: 검토할 문서 전문
        문서종류: 가정통신문 | 운영위원회회의록 | 직원회의록 | 협조공문
    """
    try:
        종류 = str(문서종류).replace(" ", "")
        items = 필수항목.get(종류)
        if not items:
            return "'" + str(문서종류) + "' 검토 기준이 아직 없어요. 지원: " + " / ".join(필수항목.keys())
        text = str(문서내용)
        checks = {
            "발신일자": bool(re.search(r"\d{4}[.\-/년]", text)),
            "구체 일정·날짜": bool(re.search(r"\d{1,2}\s*월|\d{1,2}\s*일|\d{4}[.\-/]", text)),
            "문의처": ("문의" in text or "연락" in text),
            "인사말": ("안녕" in text or "존경" in text or "사랑" in text),
        }
        found, missing = [], []
        for it in items:
            ok = checks.get(it)
            if ok is None:
                ok = any(k in text for k in re.findall(r"[가-힣]+", it))
            (found if ok else missing).append(it)
        return ("[" + str(문서종류) + " 검토 결과]\n\n✅ 포함됨: " + (", ".join(found) if found else "없음")
                + "\n\n⚠️ 빠졌을 수 있음: " + (", ".join(missing) if missing else "없음 (필수 항목 모두 포함)")
                + "\n\n※ 호스트 AI: 빠진 항목을 친절히 짚고 보완 방법을 제안하세요.")
    except Exception:
        return "검토 중 일시적 문제가 있었어요. 다시 시도해 주세요."


# ──────────────────────────────────────────────────────────────
# Tool 5. 행정 절차 안내
# ──────────────────────────────────────────────────────────────
절차_DB = {
    "운영위원회 구성": {
        "단계": ["위원 구성(보호자·교직원·지역위원)", "위원 위촉 및 명단 정리",
                "정기회의 개최(분기별 1회 이상 권장)", "회의록 작성·보관 및 결과 안내"],
        "서류": ["위원 명단", "위촉 문서", "회의록"],
        "근거확인": "구성·정족수·주기는 search_law_and_guidelines로 보육사업안내 최신본 확인",
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
    [용도] 무엇을 어떤 순서로 해야 하는지 알려줍니다.

    Args:
        업무: 안내받을 업무명 (예: "신규 교사 채용", "운영위원회 구성")
    """
    try:
        매칭 = None
        for key in 절차_DB:
            if key in str(업무) or str(업무) in key or any(w in str(업무) for w in key.split()):
                매칭 = key
                break
        if not 매칭:
            return ("'" + str(업무) + "' 절차는 아직 등록 전이에요. 현재 등록: " + " / ".join(절차_DB.keys())
                    + "\n(다른 업무는 search_law_and_guidelines로 지침에서 근거를 찾아볼 수 있어요.)")
        p = 절차_DB[매칭]
        단계 = "\n".join("  " + str(i) + ". " + s for i, s in enumerate(p["단계"], 1))
        return ("[" + 매칭 + " — 행정 절차]\n\n▷ 진행 단계\n" + 단계 + "\n\n▷ 필요 서류: " + ", ".join(p["서류"])
                + "\n▷ 근거 확인: " + p["근거확인"])
    except Exception:
        return "안내 중 일시적 문제가 있었어요. 다시 시도해 주세요."


# ──────────────────────────────────────────────────────────────
# Tool 6. 놀이흐름도 설계 (2024 개정 표준보육과정 5개 영역 기반)
# ──────────────────────────────────────────────────────────────
영역5 = "신체운동·건강 / 의사소통 / 사회관계 / 예술경험 / 자연탐구"


@mcp.tool()
def create_play_flow(놀이주제: str, 연령: str = "2세", 자료: str = "", 중심영역: str = "") -> str:
    """놀이중심·비구조화 놀이 기반 '놀이흐름도'를 2024 개정 표준보육과정 틀로 설계합니다.

    [트리거] "놀이흐름도", "놀이 설계", "놀이안", "흐름도 짜줘", "비구조화 놀이", "놀이 계획"
    [용도] 놀이 관찰 → 배움읽기(5개 영역 연결) → 교사의 지원 → 다음 놀이 지원 흐름의
          설계 프레임을 제공합니다. 호스트 AI가 연령·주제에 맞춰 구체화하세요.

    Args:
        놀이주제: 주제/소재 (예: "가을 낙엽", "상자")
        연령: 대상 (예: "2세", "0-1세", "3-5세")
        자료: 사용할 비정형 놀이자료(열린 자료)
        중심영역: 강조할 표준보육과정 영역
    """
    try:
        자료줄 = ("제공 자료: " + str(자료) + "\n") if 자료 else "제공 자료: (비정형 놀이자료 / 영유아가 자유롭게 선택)\n"
        영역줄 = ("중심 영역: " + str(중심영역) + "\n") if 중심영역 else ""
        return (
            "[놀이흐름도]  주제: " + str(놀이주제) + "  /  대상: " + str(연령) + "\n" + 자료줄 + 영역줄
            + "표준보육과정 5개 영역: " + 영역5 + "\n\n"
            "① 놀이 관찰 — 영유아가 무엇에 어떻게 몰입하는지 그대로 관찰 (개입·발문 최소화)\n"
            "② 배움읽기 — 놀이 속 영유아의 배움을 5개 영역과 연결해 읽기 "
            "(예: 자료를 쌓고 무너뜨림 → 자연탐구·신체운동·건강)\n"
            "③ 교사의 지원 — 공간·자료·시간·상호작용으로 놀이를 지원 (지시가 아니라 지원)\n"
            "④ 다음 놀이 지원 — 관찰·배움읽기를 토대로 내일의 놀이 환경·자료를 계획\n\n"
            "※ 비구조화 놀이: 정해진 정답 흐름이 아니라 영유아가 주도하는 '가능성의 지도'. "
            "호스트 AI는 " + str(연령) + "·" + str(놀이주제) + "에 맞춰 구체화하고, 영역 연계 근거는 "
            "search_law_and_guidelines(표준보육과정)로 보강하세요."
        )
    except Exception:
        return "설계 중 일시적 문제가 있었어요. 주제를 다시 입력해 주세요."


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
