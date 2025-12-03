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
            # 기본 설정
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

    # ------------------------------------------------------------------
    # 기능별 메서드
    # ------------------------------------------------------------------

    async def generate_meeting_summary(self, transcript):
        template = self.prompts.get('meeting_summary', "Error: Prompt not found")
        prompt = template.format(transcript=transcript)
        
        logger.info("Generating Meeting Summary...")
        # 요약은 JSON 포맷
        try:
            res = await self.generate_content(prompt, is_json=True)
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I)
            res_clean = re.sub(r'```\s*', '', res_clean)
            return json.loads(res_clean.strip())
        except Exception as e:
            logger.error(f"Summary Error: {e}")
            return {"title": "회의록", "summary": res, "agenda": [], "decisions": []}

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
            res = await self.generate_content(prompt, is_json=True)
            
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I)
            res_clean = re.sub(r'```\s*', '', res_clean)
            parsed = json.loads(res_clean.strip())
            
            # 리스트 방어 코드
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
                
            return parsed
            
        except Exception as e:
            logger.error(f"Review Failed: {e}")
            return {"summary": "리뷰 생성 실패", "issues": [], "suggestions": [], "score": 0}

    # ------------------------------------------------------------------
    # 비서(Assistant) 기능: Gatekeeper + RAG + Analysis
    # ------------------------------------------------------------------

    async def check_relevance(self, user_msg):
        """
        [Gatekeeper] 메시지가 봇이 반응해야 할 내용인지 판단합니다.
        (Groq 사용 권장 - 속도 및 비용 효율)
        """
        # Groq가 없거나 설정되지 않았으면 Gatekeeper 건너뛰고 바로 Gemini로 진행
        if self.provider != "groq" and not hasattr(self, 'client'):
             # 만약 Gemini만 쓰는 상황이라면 Gatekeeper를 Gemini로 돌리거나 생략할 수 있음
             # 여기서는 생략하고 True 반환
            return True 
        
        # Gatekeeper용 클라이언트는 항상 Groq를 우선 사용하도록 설정할 수도 있음 (생략)

        prompt = f"""
        You are a Gatekeeper. Determine if the bot should respond to this message.

        [Rules for YES]
        1. Project management commands/requests (tasks, meetings, github).
        2. **Casual conversation, jokes, greetings, or fun interactions.** (Allow these so the bot can be witty)
        3. Vague statements like "I'm tired", "Let's work".

        [Rules for NO]
        1. Random character strings (e.g., "asdf").
        2. Complete gibberish or spam.

        Message: "{user_msg}"
        
        Respond with ONLY 'YES' or 'NO'.
        """
        
        try:
            # Groq Client가 있으면 사용
            if hasattr(self, 'client') and self.client:
                def call():
                    return self.client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.groq_model,
                        max_tokens=5
                    ).choices[0].message.content.strip().upper()
                
                resp = await asyncio.to_thread(call)
                logger.info(f"[Gatekeeper] Input: '{user_msg}' -> Verdict: {resp}")
                return "YES" in resp
            else:
                return True
        except Exception as e:
            logger.error(f"Gatekeeper Error: {e}")
            return True 

    async def analyze_assistant_input(self, chat_context, active_tasks, projects, guild_id):
        """
        1. Gatekeeper로 관련성 확인
        2. RAG로 관련 기억 검색
        3. LLM으로 의도 파악 및 JSON 액션 생성
        """
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        projs_str = ", ".join(projects) if projects else "없음"
        
        if isinstance(chat_context, list):
            query_text = chat_context[-1] # 가장 최근 메시지
            context_msg = "\n".join(chat_context)
        else:
            query_text = chat_context
            context_msg = str(chat_context)

        # 1. Gatekeeper 체크
        is_related = await self.check_relevance(query_text)
        if not is_related:
            return {"action": "none", "comment": ""}

        # 2. [RAG] 관련 기억 검색
        relevant_memories = self.memory.query_relevant(query_text, guild_id)
        memory_context = "\n".join([f"- {m}" for m in relevant_memories]) if relevant_memories else "없음"

        # 3. 분석 프롬프트 구성
        template = self.prompts.get('assistant_analysis', "")
        augmented_msg = f"[대화 흐름]:\n{context_msg}\n\n[관련된 과거 기억(RAG)]:\n{memory_context}"

        prompt = template.format(
            projs_str=projs_str,
            tasks_str=tasks_str,
            user_msg=augmented_msg 
        )

        logger.info(f"Analyzing Assistant Input (with RAG)...")
        try:
            res = await self.generate_content(prompt, is_json=True)
            
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I)
            res_clean = re.sub(r'```\s*', '', res_clean)
            parsed_res = json.loads(res_clean.strip())
            
            # 리스트 방어 코드
            if isinstance(parsed_res, list):
                parsed_res = parsed_res[0] if parsed_res else {}
            
            logger.info(f"Assistant Action: {parsed_res.get('action')}")
            return parsed_res
            
        except Exception as e:
            logger.error(f"Assistant Analysis Failed: {e}")
            return {"action": "none", "comment": "죄송합니다, 이해하지 못했습니다."}