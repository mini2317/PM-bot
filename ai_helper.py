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

    async def generate_meeting_summary(self, transcript):
        """[변경] 제목과 회의록을 함께 생성"""
        if not self.model: return "제목: 알 수 없음\n\nAPI 키가 없습니다."

        prompt = f"""
        [대화 스크립트]:
        {transcript}

        위 내용을 분석해서 **가장 적절한 '회의 제목'**과 **'회의록'**을 작성해줘.
        
        [출력 형식]
        반드시 첫 번째 줄은 "제목: [AI가 추천하는 제목]" 형식으로 시작해야 해.
        그 다음 줄부터 회의록 내용을 작성해.

        [예시]
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

    async def extract_tasks_from_meeting(self, transcript):
        """회의록에서 할 일(Action Items)을 JSON으로 추출"""
        if not self.model: return []

        prompt = f"""
        아래 회의 대화 내용을 분석해서 '할 일(Action Items)'을 추출해줘.
        반드시 **JSON 리스트 형식**으로만 출력해. 설명이나 마크다운 없이 순수 JSON만 줘.
        
        [대화 내용]:
        {transcript}

        [출력 예시]:
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

    async def review_code(self, repo_full_name, author, message, diff_text):
        if not self.model: return "❌ API Key Missing"
        prompt = f"""
        GitHub 커밋 코드 리뷰 요청.
        Repo: {repo_full_name}, Author: {author}, Msg: {message}
        Diff: {diff_text[:15000]} 
        한국어로 1. 의도 2. 버그점검 3. 개선안 제안해줘.
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except Exception as e:
            return f"리뷰 생성 실패: {e}"