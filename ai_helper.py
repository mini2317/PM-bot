import google.generativeai as genai
import json
import re
import asyncio
import os
from groq import Groq

class AIHelper:
    def __init__(self, gemini_key, groq_key=None):
        self.gemini_key = gemini_key
        self.groq_key = groq_key
        self.load_config()
        self.load_prompts() # [NEW] 프롬프트 로드
        self.setup_client()

    def load_config(self):
        try:
            with open("src/config.json", "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except:
            self.config = {"ai_provider": "gemini", "ai_model": "gemini-2.0-flash-exp"}

    def load_prompts(self):
        """[NEW] prompts.json 파일 로드"""
        try:
            with open("prompts.json", "r", encoding="utf-8") as f:
                self.prompts = json.load(f)
        except FileNotFoundError:
            print("⚠️ prompts.json 파일을 찾을 수 없습니다. 기본값이 없으므로 오류가 발생할 수 있습니다.")
            self.prompts = {}

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
        """API 호출 통합 함수 (JSON 모드 지원)"""
        try:
            if self.provider == "gemini":
                if not self.model: return "❌ 키 설정 필요"
                # Gemini는 JSON 모드 명시 가능
                is_json = "JSON" in prompt or "json" in prompt
                config = genai.types.GenerationConfig(response_mime_type="application/json") if is_json else None
                
                response = await asyncio.to_thread(self.model.generate_content, prompt, generation_config=config)
                return response.text

            elif self.provider == "groq":
                if not hasattr(self, 'client'): return "❌ Groq 키 필요"
                
                # Groq JSON 모드
                kwargs = {
                    "messages": [{"role": "user", "content": prompt}],
                    "model": self.groq_model
                }
                if "JSON" in prompt or "json" in prompt:
                    kwargs["response_format"] = {"type": "json_object"}

                def call():
                    return self.client.chat.completions.create(**kwargs).choices[0].message.content
                
                return await asyncio.to_thread(call)
            
        except Exception as e:
            print(f"AI Generation Error: {e}")
            return f"Error: {e}"
        
        return "❌ 설정 오류"

    async def generate_meeting_summary(self, transcript):
        # 프롬프트 템플릿 로드 및 포매팅
        template = self.prompts.get('meeting_summary', "Error: Prompt not found")
        prompt = template.format(transcript=transcript)
        return await self.generate_content(prompt)

    async def extract_tasks_and_updates(self, transcript, project_structure_text, active_tasks, server_roles, members):
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        template = self.prompts.get('extract_tasks', "")
        
        # 포매팅
        prompt = template.format(
            project_structure_text=project_structure_text,
            tasks_str=tasks_str,
            server_roles=server_roles,
            members=members,
            transcript=transcript
        )

        try:
            res = await self.generate_content(prompt)
            # 마크다운 제거
            res = re.sub(r'```json\s*', '', res, flags=re.I)
            res = re.sub(r'```\s*', '', res)
            return json.loads(res.strip())
        except Exception as e:
            print(f"Task Extraction Error: {e}")
            return {}

    async def review_code(self, repo, author, msg, diff):
        template = self.prompts.get('code_review', "")
        prompt = template.format(
            repo=repo,
            author=author,
            msg=msg,
            diff=diff[:20000] # 길이 제한
        )
        try: return await self.generate_content(prompt)
        except: return "Error generating review."

    async def analyze_assistant_input(self, user_msg, active_tasks, projects):
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        projs_str = ", ".join(projects) if projects else "없음"
        
        template = self.prompts.get('assistant_analysis', "")
        prompt = template.format(
            projs_str=projs_str,
            tasks_str=tasks_str,
            user_msg=user_msg
        )

        try:
            res = await self.generate_content(prompt)
            res = re.sub(r'```json\s*', '', res, flags=re.I)
            res = re.sub(r'```\s*', '', res)
            return json.loads(res.strip())
        except:
            return {"action": "none", "comment": "죄송합니다, 이해하지 못했습니다."}