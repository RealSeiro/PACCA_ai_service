"""서버 규칙: LLM에 맡기지 않고 코드로 정하는 것들 (기획 v2 '시스템 규칙과의 역할 분리')."""
import re

_ENDINGS = ("이에요", "예요", "이요", "입니다", "이지요", "지요", "이지", "지", "이죠", "죠", "요", "이잖아", "잖아",
            "이야", "야", "인가", "같아", "인듯", "일걸", "일거야")


def normalize(text: str) -> str:
    """비교용으로 다듬기: 소문자, 공백·문장부호 제거"""
    return re.sub(r"[\s\.,!?~'\"“”‘’()\-·…]", "", (text or "").lower())


def _strip_endings(s: str) -> str:
    for _ in range(2):                       # "임영웅이요" → "임영웅", "경주인가요" → "경주"
        for e in sorted(_ENDINGS, key=len, reverse=True):
            if s.endswith(e) and len(s) > len(e):
                s = s[: -len(e)]
                break
    return s


_NEGATION_AFTER = ("아니", "아냐", "말고")
_DONT_KNOW = ("몰라", "모르", "모름")


def judge_quiz(user_answer: str, answer: str, accepted: list[str], others: list[str] = ()) -> bool:
    """퀴즈 정답 판정 (GAME-09): 문제은행의 정답·인정 표현과 비교.
    ① 다듬은 답이 정답과 같으면 정답
    ② 답 안에 정답이 들어 있으면 정답 ("아마 이미자일걸") — 단, 아래 경우는 오답:
       - 정답 바로 뒤에 부정 ("이미자 아니고 조용필")
       - "몰라"가 들어 있음 ("송대관 이미자 조용필 다 몰라")
       - 같은 분야 다른 문제의 정답도 함께 말함 (여러 개 찍기) — others"""
    said = normalize(user_answer)
    if not said:
        return False
    candidates = [normalize(a) for a in [answer, *accepted] if a]
    core = _strip_endings(said)
    if any(core == c or said == c for c in candidates):
        return True
    if any(w in said for w in _DONT_KNOW):
        return False
    hit = None
    for c in candidates:
        if len(c) >= 2 and c in said:
            hit = c
            break
    if not hit:
        return False
    after = said[said.find(hit) + len(hit):]
    if after.lstrip("이가은는도").startswith(_NEGATION_AFTER):
        return False
    for o in (normalize(x) for x in others):
        if len(o) >= 2 and o in said and o not in hit and hit not in o:
            return False
    return True


MIN_EVIDENCE = 6          # 근거는 최소 이만큼 (글자, 공백 제외). 단, 어르신 말 전체가 더 짧으면 그 말 전체
MIN_OVERLAP = 0.25        # 저장할 문장(content)의 두 글자 조각 중 근거에 들어 있어야 하는 비율


def _bigrams(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[0-9A-Za-z가-힣]+", (text or "").lower()):
        out.update(w[i:i + 2] for i in range(len(w) - 1))
    return out


def evidence_ok(evidence: str, elder_texts: list[str], content: str | None = None) -> bool:
    """기억·일상 '후보'가 이번 대화에서 어르신이 실제로 한 말에 근거하는지 (허위 기억 방지)
    ① 근거(evidence)가 어르신 말 안에 그대로 있다 (너무 짧은 조각은 안 됨: "어요", "점심" 같은 것)
    ② 저장할 문장(content)이 근거와 내용이 겹친다 — 근거만 진짜고 content는 지어낸 경우를 막음"""
    ev = normalize(evidence)
    said = [normalize(t) for t in elder_texts]
    if not ev or not any(ev in t for t in said):
        return False
    if len(ev) < MIN_EVIDENCE and ev not in said:
        return False
    if content is not None:
        cb = _bigrams(content)
        if cb:
            ev_text = normalize(evidence)
            overlap = sum(1 for b in cb if b in ev_text)
            if overlap == 0 or overlap / len(cb) < MIN_OVERLAP:
                return False
    return True
