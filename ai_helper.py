import google.generativeai as genai
import json
import re
import asyncio
import os
import logging
from groq import Groq

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
            # [Fix] 기본 모델을 최신 지원 모델로 변경
            self.config = {"ai_provider": "gemini", "ai_model": "gemini-2.0-flash-exp", "groq_model": "llama-3.3-70b-versatile"}

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
            self.model = genai.GenerativeModel(self.config.get("ai_model", "gemini-2.0-flash-exp"))
            logger.info(f"Gemini Client Setup Complete. Model: {self.config.get('ai_model')}")
        elif self.provider == "groq" and self.groq_key:
            self.client = Groq(api_key=self.groq_key)
            # [Fix] config.json에 값이 없을 경우를 대비해 기본값도 최신 모델로 변경
            self.groq_model = self.config.get("groq_model", "llama-3.3-70b-versatile")
            logger.info(f"Groq Client Setup Complete. Model: {self.groq_model}")
        else:
            logger.error("❌ AI Provider 설정 오류 또는 키 누락")
            self.model = None

    async def generate_content(self, prompt, is_json=False):
        """API 호출 통합 함수 (JSON 모드 명시적 처리)"""
        try:
            logger.debug(f"Generating content... (JSON Mode: {is_json})")
            
            if self.provider == "gemini":
                if not self.model: return "❌ 키 설정 필요"
                
                config = genai.types.GenerationConfig(
                    response_mime_type="application/json"
                ) if is_json else None
                
                response = await asyncio.to_thread(
                    self.model.generate_content, 
                    prompt, 
                    generation_config=config
                )
                return response.text

            elif self.provider == "groq":
                if not hasattr(self, 'client'): return "❌ Groq 키 필요"
                
                kwargs = {
                    "messages": [{"role": "user", "content": prompt}],
                    "model": self.groq_model
                }
                if is_json:
                    kwargs["response_format"] = {"type": "json_object"}

                def call():
                    return self.client.chat.completions.create(**kwargs).choices[0].message.content
                
                return await asyncio.to_thread(call)
            
        except Exception as e:
            logger.error(f"AI Generation Error: {e}", exc_info=True)
            return f"Error: {e}"
        
        return "❌ 설정 오류"

    async def generate_meeting_summary(self, transcript):
        template = self.prompts.get('meeting_summary', "Error: Prompt not found")
        prompt = template.format(transcript=transcript)
        
        logger.info("Generating Meeting Summary...")
        result = await self.generate_content(prompt, is_json=False)
        return result

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

        logger.info("Extracting tasks from meeting...")
        try:
            res = await self.generate_content(prompt, is_json=True)
            
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I)
            res_clean = re.sub(r'```\s*', '', res_clean)
            parsed = json.loads(res_clean.strip())
            
            logger.debug(f"Extracted Data: {json.dumps(parsed, indent=2, ensure_ascii=False)}")
            return parsed
            
        except Exception as e:
            logger.error(f"Task Extraction Failed: {e}")
            logger.debug(f"Raw Response: {res}")
            return {}

    async def review_code(self, repo, author, msg, diff):
        template = self.prompts.get('code_review', "")
        prompt = template.format(
            repo=repo,
            author=author,
            msg=msg,
            diff=diff[:20000]
        )
        logger.info(f"Reviewing code for {repo}...")
        try:
            # JSON 모드로 호출
            res = await self.generate_content(prompt, is_json=True)
            
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I)
            res_clean = re.sub(r'```\s*', '', res_clean)
            parsed = json.loads(res_clean.strip())
            return parsed
            
        except Exception as e:
            logger.error(f"Review Failed: {e}")
            return {"summary": "리뷰 생성 실패", "issues": [], "suggestions": [], "score": 0}

    async def analyze_assistant_input(self, chat_context, rich_context):
        """
        [UPDATE] rich_context: 프로젝트 구조와 할 일이 통합된 텍스트
        """
        # 리스트로 들어온 경우 줄바꿈으로 연결
        if isinstance(chat_context, list):
            context_msg = "\n".join(chat_context)
        else:
            context_msg = str(chat_context)
        
        template = self.prompts.get('assistant_analysis', "")
        
        # 프롬프트 내 변수명도 변경 필요 (prompts.json 수정 필요)
        # 여기서는 기존 포맷을 무시하고 새로운 context로 덮어씌우는 방식 예시
        prompt = f"""
        당신은 프로젝트 관리 비서입니다. 
        
        [현재 프로젝트 전체 현황 (Knowledge Graph)]
        {rich_context}

        [사용자 대화 기록]
        {context_msg}

        위 정보를 바탕으로 사용자의 의도를 파악하여 JSON 액션을 생성하세요.
        (지원 액션: create_project, add_task, complete_task, assign_task 등 기존과 동일)
        
        [출력]: 오직 JSON 형식.
        """

        # 실제로는 prompts.json을 수정해서 {rich_context}를 받게 하는 것이 가장 깔끔합니다.
        # 아래는 호환성을 위해 기존 함수 호출 방식을 유지하되 내용을 rich_context로 대체하는 꼼수
        # prompt = template.format(projs_str="[참조]", tasks_str=rich_context, user_msg=context_msg)
        
        try:
            res = await self.generate_content(prompt, is_json=True)
            
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I)
            res_clean = re.sub(r'```\s*', '', res_clean)
            parsed_res = json.loads(res_clean.strip())
            
            logger.info(f"Assistant Thought: {parsed_res.get('comment', 'No comment')} (Action: {parsed_res.get('action')})")
            return parsed_res
            
        except Exception as e:
            logger.error(f"Assistant Analysis Failed: {e}")
            return {"action": "none", "comment": "죄송합니다, 이해하지 못했습니다."}