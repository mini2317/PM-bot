import google.generativeai as genai
import json
import re
import asyncio
import os
import logging
from groq import Groq
from services.memory import MemoryService

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIHelper")

class AIHelper:
    def __init__(self, gemini_key, groq_key=None):
        self.gemini_key = gemini_key
        self.groq_key = groq_key
        self.load_config()
        self.load_prompts()
        self.setup_client()
        self.memory = MemoryService() # 메모리 서비스(RAG)

    def load_config(self):
        try:
            with open("src/config.json", "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except:
            # [Update] Groq 테스트를 위해 기본 설정을 Groq로 변경
            self.config = {"ai_provider": "groq", "ai_model": "gemini-1.5-pro", "groq_model": "llama-3.3-70b-versatile"}

    def load_prompts(self):
        try:
            with open("prompts.json", "r", encoding="utf-8") as f:
                self.prompts = json.load(f)
        except FileNotFoundError:
            logger.warning("⚠️ prompts.json 파일을 찾을 수 없습니다.")
            self.prompts = {}

    def setup_client(self):
        self.provider = self.config.get("ai_provider", "groq") # 기본값 Groq
        
        # Gemini 설정
        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self.model = genai.GenerativeModel(self.config.get("ai_model", "gemini-1.5-pro"))
        else:
            self.model = None

        # Groq 설정
        if self.groq_key:
            self.client = Groq(api_key=self.groq_key)
            self.groq_model = self.config.get("groq_model", "llama-3.3-70b-versatile")
        else:
            self.client = None

        logger.info(f"AI Client Setup Complete. Provider: {self.provider}")

    async def generate_content(self, prompt, is_json=False):
        """API 호출 통합 함수"""
        try:
            logger.debug(f"Generating content... (JSON Mode: {is_json})")
            
            if self.provider == "gemini":
                if not self.model: return "❌ 키 설정 필요"
                config = genai.types.GenerationConfig(response_mime_type="application/json") if is_json else None
                response = await asyncio.to_thread(self.model.generate_content, prompt, generation_config=config)
                return response.text

            elif self.provider == "groq":
                if not self.client: return "❌ Groq 키 필요"
                
                kwargs = {"messages": [{"role": "user", "content": prompt}], "model": self.groq_model}
                if is_json: kwargs["response_format"] = {"type": "json_object"}

                def call():
                    return self.client.chat.completions.create(**kwargs).choices[0].message.content
                
                return await asyncio.to_thread(call)
            
        except Exception as e:
            logger.error(f"AI Generation Error: {e}", exc_info=True)
            return f"Error: {e}"

    async def generate_meeting_summary(self, transcript):
        template = self.prompts.get('meeting_summary', "Error: Prompt not found")
        prompt = template.format(transcript=transcript)
        return await self.generate_content(prompt, is_json=False)

    async def extract_tasks_and_updates(self, transcript, project_structure_text, active_tasks, server_roles, members):
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        template = self.prompts.get('extract_tasks', "")
        prompt = template.format(
            project_structure_text=project_structure_text,
            tasks_str=tasks_str,
            server_roles=server_roles,
            members=members,
            transcript=transcript
        )
        try:
            res = await self.generate_content(prompt, is_json=True)
            res = re.sub(r'```json\s*', '', res, flags=re.I)
            res = re.sub(r'```\s*', '', res)
            return json.loads(res.strip())
        except: return {}

    async def review_code(self, repo, author, msg, diff):
        template = self.prompts.get('code_review', "")
        prompt = template.format(repo=repo, author=author, msg=msg, diff=diff[:20000])
        try:
            res = await self.generate_content(prompt, is_json=True)
            res = re.sub(r'```json\s*', '', res, flags=re.I)
            res = re.sub(r'```\s*', '', res)
            parsed = json.loads(res.strip())
            if isinstance(parsed, list): parsed = parsed[0] if parsed else {}
            return parsed
        except: return {"summary": "실패", "issues": [], "suggestions": [], "score": 0}

    # [NEW] 1차 필터링 (Gatekeeper)
    async def check_relevance(self, user_msg):
        """메시지가 프로젝트 관리와 관련이 있는지 빠르게 판단 (True/False)"""
        # Groq가 없으면 그냥 통과 (Gemini로 처리)
        if not self.client: return True
        
        prompt = f"""
        Check if the message is related to project management, tasks, meetings, code, github, or bot commands.
        Message: "{user_msg}"
        Reply only 'YES' or 'NO'.
        """
        try:
            # 아주 가벼운 호출
            def call():
                return self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.groq_model,
                    max_tokens=5
                ).choices[0].message.content.strip().upper()
            
            resp = await asyncio.to_thread(call)
            return "YES" in resp
        except: return True

    async def analyze_assistant_input(self, chat_context, active_tasks, projects, guild_id):
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        projs_str = ", ".join(projects) if projects else "없음"
        
        if isinstance(chat_context, list):
            query_text = chat_context[-1] # 가장 최근 메시지
            context_msg = "\n".join(chat_context)
        else:
            query_text = chat_context
            context_msg = str(chat_context)

        # [Step 1] 관련성 체크 (Gatekeeper)
        is_related = await self.check_relevance(query_text)
        if not is_related:
            logger.info("Gatekeeper: 잡담 무시")
            return {"action": "none", "comment": ""}

        # [Step 2] 관련있으면 RAG 검색 및 분석
        relevant_memories = self.memory.query_relevant(query_text, guild_id)
        memory_context = "\n".join([f"- {m}" for m in relevant_memories]) if relevant_memories else "없음"

        template = self.prompts.get('assistant_analysis', "")
        augmented_msg = f"[대화]:\n{context_msg}\n[기억]:\n{memory_context}"

        prompt = template.format(
            projs_str=projs_str,
            tasks_str=tasks_str,
            user_msg=augmented_msg 
        )

        logger.info(f"Analyzing Input...")
        try:
            res = await self.generate_content(prompt, is_json=True)
            res = re.sub(r'```json\s*', '', res, flags=re.I)
            res = re.sub(r'```\s*', '', res)
            parsed = json.loads(res.strip())
            if isinstance(parsed, list): parsed = parsed[0] if parsed else {}
            return parsed
        except: return {"action": "none", "comment": "이해 실패"}