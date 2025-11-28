import google.generativeai as genai
import json
import re
import asyncio

class AIHelper:
    def __init__(self, api_key):
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
        else:
            self.model = None

    async def generate_meeting_summary(self, formatted_transcript):
        """
        [변경] 구조화된 대화 로그를 기반으로 요약 및 제목 생성
        formatted_transcript 예시:
        [Speaker: 홍길동 | Time: 12:00] 안녕하세요
        [Speaker: 김철수 | Time: 12:01] 반갑습니다
        """
        if not self.model: return "제목: 알 수 없음\n\nAPI 키가 없습니다."

        prompt = f"""
        당신은 전문 프로젝트 매니저(PM)입니다. 
        아래 제공되는 회의 대화 로그는 `[Speaker: 이름 | Time: 시간] 발언 내용` 형식으로 구조화되어 있습니다.
        이 정보를 바탕으로 **누가 어떤 의견을 냈는지** 맥락을 정확히 파악하여 회의록을 작성하세요.

        [대화 로그]:
        {formatted_transcript}

        [요청 사항]
        1. **가장 적절한 '회의 제목'**을 첫 줄에 작성하세요. (형식: "제목: [제목내용]")
        2. 그 다음 줄부터 **회의록**을 작성하세요.
        3. 요약 시, 중요한 결정 사항에는 발언자 이름을 괄호 안에 명시하세요. 예: "API 스펙 확정 (김철수)"

        [출력 예시]
        제목: 11월 4주차 로그인 API 설계 회의
        
        # 📅 회의록
        ## 1. 3줄 요약
        ...
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except Exception as e:
            return f"제목: 에러 발생\n\n오류 내용: {e}"

    async def extract_tasks_from_meeting(self, formatted_transcript):
        """구조화된 로그에서 할 일 추출"""
        if not self.model: return []

        prompt = f"""
        아래 회의 대화 내용을 분석해서 '할 일(Action Items)'을 추출해줘.
        대화는 `[Speaker: 이름]` 형식으로 구분되어 있으니, 이를 참고하여 **담당자(assignee_hint)**를 최대한 추론해줘.
        
        [대화 로그]:
        {formatted_transcript}

        [출력 형식]: JSON 리스트만 출력 (마크다운 없이).
        [
            {{"content": "로그인 페이지 UI 디자인", "assignee_hint": "김철수"}},
            {{"content": "API 명세서 작성", "assignee_hint": ""}}
        ]
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            text = response.text
            text = re.sub(r'```json\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = text.strip()
            tasks = json.loads(text)
            return tasks
        except Exception as e:
            print(f"Task Extraction Error: {e}")
            return []

    async def review_code(self, repo, author, msg, diff):
        if not self.model: return "❌ API Key Missing"
        prompt = f"""
        GitHub Code Review.
        Repo: {repo}, Author: {author}, Msg: {msg}
        Diff: {diff[:15000]}
        Language: Korean. Check intent, bugs, and improvements.
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except: return "Error generating review."