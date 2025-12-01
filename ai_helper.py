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
        if not self.model: return "제목: 알 수 없음\n\nAPI 키가 없습니다."
        prompt = f"당신은 PM입니다. 한국어로 회의록을 작성하세요. 첫 줄은 '제목: [제목]' 형식입니다.\n\n[대화]:\n{transcript}"
        try: return (await asyncio.to_thread(self.model.generate_content, prompt)).text
        except Exception as e: return f"에러: {e}"

    async def extract_tasks_and_updates(self, transcript, project_structure_text, active_tasks, server_roles, members):
        """
        [UPDATE] AI의 눈치를 대폭 상향시켰습니다.
        소극적인 태도 금지, 적극적/추론적 할 일 생성, 역할 강제 추출.
        """
        if not self.model: return {}

        tasks_str = json.dumps(active_tasks, ensure_ascii=False)

        prompt = f"""
        회의 대화 내용을 분석하여 프로젝트 관리 정보를 JSON으로 추출하세요.

        [🚨 최우선 지시사항]
        1. **과할 정도로 적극적으로 추출하세요**: 확정된 사항뿐만 아니라 지시, 압박, 제안, 아이디어도 모두 실행 가능한 항목으로 변환하세요.
        2. **프로젝트 이름 주의**: 컨텍스트에 제공된 프로젝트 이름들은 각각 별개의 프로젝트입니다. 'A, B'는 'A'와 'B' 두 개이지, 'A, B'라는 이름의 프로젝트가 아닙니다.
        
        [컨텍스트 정보]
        1. 프로젝트 구조(트리): 
        {project_structure_text}
        (위 구조에 없는 새로운 주제라면 과감하게 새 프로젝트 이름을 제안하세요.)

        2. 진행 작업: {tasks_str}
        3. 서버 역할: {server_roles}
        4. 멤버: {members}

        [입력 대화]:
        {transcript}

        [출력 포맷 (JSON Only)]:
        {{
            "new_tasks": [
                {{"content": "할 일 내용", "project": "프로젝트명(기존or신규)", "assignee_hint": "추정 담당자", "is_new_project": true/false, "suggested_parent": "상위프로젝트명(없으면 null)"}}
            ],
            "updates": [],
            "create_roles": ["필요한역할명"],
            "assign_roles": [{{"member_name": "멤버", "role_name": "역할"}}]
        }}
        """
        try:
            config = genai.types.GenerationConfig(response_mime_type="application/json")
            
            response = await asyncio.to_thread(
                self.model.generate_content, 
                prompt, 
                generation_config=config
            )
            
            text = response.text
            text = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
            text = re.sub(r'```\s*', '', text)
            
            return json.loads(text.strip())
            
        except json.JSONDecodeError as je:
            print(f"AI JSON Parsing Error: {je}")
            return {}
        except Exception as e:
            print(f"AI Error: {e}")
            return {}

    async def review_code(self, repo, author, msg, diff):
        if not self.model: return "❌ Key Missing"
        prompt = f"GitHub Review.\nRepo:{repo}, User:{author}, Msg:{msg}\nDiff:{diff[:20000]}\한국어로 답변해."
        try: return (await asyncio.to_thread(self.model.generate_content, prompt)).text
        except: return "Error"