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

    async def generate_meeting_summary(self, meeting_name, transcript):
        """회의록 텍스트 요약 생성"""
        if not self.model: return "❌ API Key Missing"

        prompt = f"""
        [회의 주제]: {meeting_name}
        [대화 스크립트]:
        {transcript}

        위 내용을 바탕으로 아래 양식의 회의록을 작성해줘. 한국어로 작성해.
        
        # 📅 {meeting_name} 회의록
        
        ## 1. 3줄 요약
        ## 2. 주요 논의사항
        ## 3. 결정된 사항
        ## 4. 향후 할 일 (Assignee 포함)
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except Exception as e:
            return f"오류 발생: {e}"

    async def extract_tasks_from_meeting(self, transcript):
        """(Task 2) 회의록에서 할 일(Action Items)을 JSON으로 추출"""
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
            
            # 마크다운 코드 블록 제거 (```json ... ```)
            text = re.sub(r'```json\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = text.strip()
            
            tasks = json.loads(text)
            return tasks
        except Exception as e:
            print(f"Task Extraction Error: {e}")
            return []

    async def review_code(self, repo_full_name, author, message, diff_text):
        """코드 리뷰 생성"""
        if not self.model: return "❌ API Key Missing"

        prompt = f"""
        GitHub 커밋 코드 리뷰 요청.
        [Commit Info] Repo: {repo_full_name}, Author: {author}, Msg: {message}
        [Code Diff]
        {diff_text[:15000]} 

        [리뷰 가이드]
        1. 코드 의도 파악
        2. 잠재적 버그/성능 문제 지적
        3. 개선안 제안
        4. 친절한 한국어로 답변
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except Exception as e:
            return f"리뷰 생성 실패: {e}"