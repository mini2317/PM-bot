import google.generativeai as genai
import json
import re
import asyncio
import os
import logging
from groq import Groq

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
        except FileNotFoundError:
            logger.warning("⚠️ prompts.json 파일을 찾을 수 없습니다.")
            self.prompts = {}

    def setup_client(self):
        self.provider = self.config.get("ai_provider", "gemini")
        if self.provider == "gemini" and self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self.model = genai.GenerativeModel(self.config.get("ai_model", "gemini-1.5-pro"))
            logger.info(f"Gemini Client Setup Complete. Model: {self.config.get('ai_model')}")
        elif self.provider == "groq" and self.groq_key:
            self.client = Groq(api_key=self.groq_key)
            self.groq_model = self.config.get("groq_model", "llama-3.3-70b-versatile")
            logger.info(f"Groq Client Setup Complete. Model: {self.groq_model}")
        else:
            logger.error("❌ AI Provider 설정 오류 또는 키 누락")
            self.model = None

    async def generate_content(self, prompt, is_json=False):
        try:
            logger.debug(f"Generating content... (JSON Mode: {is_json})")
            if self.provider == "gemini":
                if not self.model: return "❌ 키 설정 필요"
                config = genai.types.GenerationConfig(response_mime_type="application/json") if is_json else None
                response = await asyncio.to_thread(self.model.generate_content, prompt, generation_config=config)
                return response.text
            elif self.provider == "groq":
                if not hasattr(self, 'client'): return "❌ Groq 키 필요"
                final_prompt = prompt
                if is_json and "json" not in prompt.lower():
                    final_prompt += "\n\n(IMPORTANT: Respond in JSON format)"
                kwargs = {"messages": [{"role": "user", "content": final_prompt}], "model": self.groq_model}
                if is_json: kwargs["response_format"] = {"type": "json_object"}
                def call(): return self.client.chat.completions.create(**kwargs).choices[0].message.content
                return await asyncio.to_thread(call)
        except Exception as e:
            logger.error(f"AI Generation Error: {e}", exc_info=True)
            return f"Error: {e}"
        return "❌ 설정 오류"

    async def generate_meeting_summary(self, transcript):
        template = self.prompts.get('meeting_summary', "Error: Prompt not found")
        # [FIX] template을 바로 넘기지 않고 format을 먼저 수행
        prompt = template.format(transcript=transcript)
        
        logger.info("Generating Meeting Summary...")
        try:
            res = await self.generate_content(prompt, is_json=True)
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I).replace('```', '')
            parsed = json.loads(res_clean.strip())
            if isinstance(parsed, list): parsed = parsed[0] if parsed else {}
            return parsed
        except Exception as e:
            logger.error(f"Summary Error: {e}")
            return {"title": "회의록", "summary": str(res), "agenda": [], "decisions": []}

    # [UPDATE] members 인자 추가
    async def extract_tasks_and_updates(self, transcript, current_project, active_tasks, members):
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        template = self.prompts.get('extract_tasks', "")
        
        # [UPDATE] members 포맷팅 추가
        prompt = template.format(
            current_project=current_project,
            tasks_str=tasks_str,
            transcript=transcript,
            members=members
        )

        logger.info("Extracting tasks from meeting...")
        try:
            res = await self.generate_content(prompt, is_json=True)
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I).replace('```', '')
            parsed = json.loads(res_clean.strip())
            return parsed
        except Exception as e:
            logger.error(f"Task Extraction Failed: {e}")
            return {}

    async def review_code(self, repo, author, msg, diff):
        template = self.prompts.get('code_review', "")
        prompt = template.format(repo=repo, author=author, msg=msg, diff=diff[:20000])
        logger.info(f"Reviewing code...")
        try:
            res = await self.generate_content(prompt, is_json=True)
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I).replace('```', '')
            parsed = json.loads(res_clean.strip())
            if isinstance(parsed, list): parsed = parsed[0] if parsed else {}
            return parsed
        except Exception as e:
            logger.error(f"Review Failed: {e}")
            return {"summary": "실패", "issues": [], "suggestions": [], "score": 0}