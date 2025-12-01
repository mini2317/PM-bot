import google.generativeai as genai
import json
import re
import asyncio
from groq import Groq

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
            self.model = None

    async def generate_content(self, prompt):
        if self.provider == "gemini":
            if not self.model: return "❌ 키 설정 필요"
            return (await asyncio.to_thread(self.model.generate_content, prompt)).text
        elif self.provider == "groq":
            if not hasattr(self, 'client'): return "❌ Groq 키 필요"
            def call():
                return self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.groq_model
                ).choices[0].message.content
            return await asyncio.to_thread(call)
        return "❌ 설정 오류"

    async def generate_meeting_summary(self, transcript):
        prompt = f"당신은 PM입니다. 회의록을 작성하세요. 첫 줄: '제목: [제목]'\n\n{transcript}"
        return await self.generate_content(prompt)

    async def extract_tasks_and_updates(self, transcript, proj_struct, active_tasks, roles, members):
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        prompt = f"""
        회의 내용을 분석하여 프로젝트 정보를 JSON으로 추출하세요.
        컨텍스트: 프로젝트구조({proj_struct}), 진행작업({tasks_str}), 역할({roles}), 멤버({members})
        
        [요청] 할일(new_tasks), 상태변경(updates), 역할생성(create_roles), 역할부여(assign_roles) 추출.
        반드시 순수 JSON만 출력하세요.
        
        [입력]: {transcript}
        """
        try:
            res = await self.generate_content(prompt)
            res = re.sub(r'```json\s*', '', res, flags=re.I)
            res = re.sub(r'```\s*', '', res)
            return json.loads(res.strip())
        except: return {}

    async def review_code(self, repo, author, msg, diff):
        prompt = f"Code Review.\nRepo:{repo}, User:{author}, Msg:{msg}\nDiff:{diff[:20000]}\nKorean response."
        try: return await self.generate_content(prompt)
        except: return "Error"

    # [NEW] 비서 모드: 자연어 명령 해석
    async def analyze_assistant_input(self, user_msg, active_tasks):
        """
        사용자의 채팅을 분석하여 DB 조작 의도를 파악합니다.
        """
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        prompt = f"""
        당신은 프로젝트 관리 비서입니다. 사용자의 말을 듣고 수행할 작업을 JSON으로 판단하세요.
        
        [현재 진행 중인 작업 목록]:
        {tasks_str}

        [사용자 입력]: "{user_msg}"

        [지시사항]
        1. 사용자가 **할 일을 완료**했다고 하면 `complete_task` 액션을 반환하세요. (유사한 작업 내용을 찾아 ID 매핑)
        2. **새로운 할 일**을 시키면 `add_task` 액션을 반환하세요.
        3. **담당자 변경**을 말하면 `assign_task` 액션을 반환하세요.
        4. 단순히 잡담이나 불명확한 말이면 `none`을 반환하세요.
        5. **반드시 JSON 포맷**으로만 응답하세요.

        [출력 예시]
        - 완료 시: {{ "action": "complete_task", "task_id": 12, "comment": "로그인 구현 완료 처리했습니다." }}
        - 추가 시: {{ "action": "add_task", "content": "버그 수정", "project": "유지보수", "comment": "버그 수정 작업을 추가했습니다." }}
        - 잡담 시: {{ "action": "none", "comment": "네, 알겠습니다." }}
        """
        try:
            res = await self.generate_content(prompt)
            res = re.sub(r'```json\s*', '', res, flags=re.I)
            res = re.sub(r'```\s*', '', res)
            return json.loads(res.strip())
        except: return {"action": "none", "comment": "죄송합니다, 이해하지 못했습니다."}