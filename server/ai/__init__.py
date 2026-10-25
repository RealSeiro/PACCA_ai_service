"""서버가 부르는 AI 함수의 입구. 약속(입력·출력 모양)은 ai/contract.py 참고.
곽민석 님의 진짜 AI가 준비되면 아래 import 한 줄만 바꾸면 된다. (예: from .llm import ...)"""
from .fake import respond, summarize_day  # noqa: F401
