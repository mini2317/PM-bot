import google.generativeai as genai
import json
import re
import asyncio
import logging
from groq import Groq
from services.memory import MemoryService

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIHelper")

class AIHelper:
    def __init__(self, gemini_key, groq_key=None):
        self.gemini_key = gemini_key
        self.groq_key = groq_key
        self.load_config()
        self.load_prompts()
        self.setup_client()
        self.memory = MemoryService()

    def load_config(self):
        try:
            with open("src/config.json", "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except:
            self.config = {"ai_provider": "gemini", "ai_model": "gemini-1.5-pro", "groq_model": "llama-3.3-70b-versatile"}

    def load_prompts(self):
        try:
            with open("prompts.json", "r", encoding="utf-8") as f:
                self.prompts = json.load(f)
        except: self.prompts = {}

    def setup_client(self):
        self.provider = self.config.get("ai_provider", "gemini")
        if self.provider == "gemini" and self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self.model = genai.GenerativeModel(self.config.get("ai_model", "gemini-1.5-pro"))
        elif self.provider == "groq" and self.groq_key:
            self.client = Groq(api_key=self.groq_key)
            self.groq_model = self.config.get("groq_model", "llama-3.3-70b-versatile")
        else: self.model = None

    async def generate_content(self, prompt, is_json=False):
        try:
            if self.provider == "gemini":
                if not self.model: return "Err: No Key"
                config = genai.types.GenerationConfig(response_mime_type="application/json") if is_json else None
                res = await asyncio.to_thread(self.model.generate_content, prompt, generation_config=config)
                return res.text
            elif self.provider == "groq":
                if not hasattr(self, 'client'): return "Err: No Key"
                kw = {"messages": [{"role": "user", "content": prompt}], "model": self.groq_model}
                if is_json: kw["response_format"] = {"type": "json_object"}
                def call(): return self.client.chat.completions.create(**kw).choices[0].message.content
                return await asyncio.to_thread(call)
        except Exception as e: return f"Err: {e}"
        return "Err"

    async def generate_meeting_summary(self, transcript):
        # [UPDATE] 회의록은 JSON 포맷 유지 (PDF 생성용)
        prompt = self.prompts.get('meeting_summary', "").format(transcript=transcript)
        try:
            res = await self.generate_content(prompt, is_json=True)
            return json.loads(res)
        except: return {"title": "오류", "summary": res}

    async def extract_tasks_and_updates(self, transcript, proj, active, roles, mems):
        # 회의 분석도 PML로 하면 좋겠지만, MeetingCog 로직을 많이 바꿔야 하므로 일단 JSON 유지하거나
        # 여기서는 기존 로직 호환성을 위해 JSON 유지.
        # (사용자 요청은 "비서" 기능이므로 analyze_assistant_input에 집중)
        tasks_str = json.dumps(active, ensure_ascii=False)
        prompt = self.prompts.get('extract_tasks', "").format(project_structure_text=proj, tasks_str=tasks_str, server_roles=roles, members=mems, transcript=transcript)
        try:
            res = await self.generate_content(prompt, is_json=True)
            return json.loads(res)
        except: return {}

    async def review_code(self, r, a, m, d):
        prompt = self.prompts.get('code_review', "").format(repo=r, author=a, msg=m, diff=d[:20000])
        try:
            res = await self.generate_content(prompt, is_json=True)
            return json.loads(res)
        except: return {}

    async def analyze_assistant_input(self, chat_context, active_tasks, projects, guild_id):
        """
        [UPDATE] JSON 대신 PML 스크립트 텍스트 반환
        """
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        projs_str = ", ".join(projects) if projects else "없음"
        
        ctx_msg = "\n".join(chat_context) if isinstance(chat_context, list) else str(chat_context)
        
        # RAG
        mems = self.memory.query_relevant(ctx_msg, guild_id)
        mem_ctx = "\n".join([f"- {m}" for m in mems]) if mems else "없음"

        prompt = self.prompts.get('assistant_analysis', "").format(
            projs_str=projs_str, tasks_str=tasks_str, user_msg=f"{ctx_msg}\n[기억]: {mem_ctx}"
        )

        logger.info("Generating PML Script...")
        try:
            # [FIX] is_json=False (스크립트는 텍스트임)
            script = await self.generate_content(prompt, is_json=False)
            # 마크다운 코드블록 제거
            script = script.replace("```pml", "").replace("```", "").strip()
            return script
        except Exception as e:
            logger.error(f"Analysis Failed: {e}")
            return "SAY \"오류가 발생했습니다.\""