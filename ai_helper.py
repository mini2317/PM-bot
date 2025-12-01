import google.generativeai as genai
import json
import re
import asyncio
import os
from groq import Groq # pip install groq

class AIHelper:
    def __init__(self, gemini_key, groq_key=None):
        self.gemini_key = gemini_key
        self.groq_key = groq_key
        self.load_config()
        self.setup_client()

    def load_config(self):
        try:
            with open("src/config.json", "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except:
            # 기본값
            self.config = {"ai_provider": "gemini", "ai_model": "gemini-2.0-flash-exp"}

    def setup_client(self):
        self.provider = self.config.get("ai_provider", "gemini")
        
        if self.provider == "gemini" and self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self.model = genai.GenerativeModel(self.config.get("ai_model", "gemini-2.0-flash-exp"))
        elif self.provider == "groq" and self.groq_key:
            self.client = Groq(api_key=self.groq_key)
            self.groq_model = self.config.get("groq_model", "llama3-70b-8192")
        else:
            print("⚠️ AI Provider 설정 오류 또는 키 누락")
            self.model = None

    async def generate_content(self, prompt):
        """Provider에 따른 통합 생성 함수"""
        if self.provider == "gemini":
            if not self.model: return "❌ Gemini 키 설정 필요"
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        
        elif self.provider == "groq":
            if not hasattr(self, 'client'): return "❌ Groq 키 설정 필요"
            
            def call_groq():
                completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.groq_model,
                )
                return completion.choices[0].message.content

            return await asyncio.to_thread(call_groq)
        
        return "❌ AI Provider 설정 오류"

    async def generate_meeting_summary(self, transcript):
        prompt = f"당신은 PM입니다. 한국어로 회의록을 작성하세요. 첫 줄은 '제목: [제목]' 형식입니다.\n\n[대화]:\n{transcript}"
        try: return await self.generate_content(prompt)
        except Exception as e: return f"에러: {e}"

    async def extract_tasks_and_updates(self, transcript, project_structure_text, active_tasks, server_roles, members):
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        prompt = f"""
        회의 대화 내용을 분석하여 프로젝트 관리 정보를 JSON으로 추출하세요.
        [컨텍스트]
        1. 프로젝트 구조: {project_structure_text}
        2. 진행 작업: {tasks_str}
        3. 서버 역할: {server_roles}
        4. 멤버: {members}

        [요청사항]
        적극적으로 할 일과 변경사항을 추출하세요. 출력은 오직 **순수 JSON**이어야 합니다.
        
        [입력]: {transcript}
        
        [출력 예시]:
        {{
            "new_tasks": [{{"content": "...", "project": "...", "assignee_hint": "...", "is_new_project": false, "suggested_parent": null}}],
            "updates": [{{"task_id": 12, "status": "DONE"}}],
            "create_roles": [],
            "assign_roles": []
        }}
        """
        try:
            text = await self.generate_content(prompt)
            text = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
            text = re.sub(r'```\s*', '', text)
            return json.loads(text.strip())
        except Exception as e:
            print(f"AI Extraction Error: {e}")
            return {}

    async def review_code(self, repo, author, msg, diff):
        prompt = f"GitHub Review.\nRepo:{repo}, User:{author}, Msg:{msg}\nDiff:{diff[:20000]}\nKorean response."
        try: return await self.generate_content(prompt)
        except: return "Error"