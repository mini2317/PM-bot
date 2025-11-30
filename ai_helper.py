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

        [🚨 최우선 지시사항 - 과할 정도로 적극적으로 추출하세요]
        당신은 "눈치 빠른 비서"입니다. 확정된 사항뿐만 아니라, **지시, 압박, 제안, 막연한 아이디어**까지 모두 실행 가능한 항목으로 변환하세요.
        
        1. **할 일(new_tasks) 추출 기준**:
           - "게임을 만들자" -> "게임 기획안 작성", "초기 컨셉 회의" (구체적이지 않아도 실행 가능한 첫 단계로 변환)
           - "역할 좀 정해라" -> "팀 내 R&R(역할) 정의", "담당자 배정 논의"
           - "~가 필요하다", "~해야지" -> 즉시 할 일로 등록
           - 누군가에게 압박/지시하는 말투 -> 해당 내용을 즉시 할 일로 변환
        
        2. **역할(create_roles, assign_roles) 추출 기준**:
           - "니가 팀장 해", "개발자 필요해" 등 언급이 있으면 즉시 추출
           - 문맥상 특정인이 주도적으로 말하면 'PM'이나 '리더' 역할을 제안해볼 것

        [컨텍스트]
        1. 프로젝트 구조: {project_structure_text}
        2. 진행 작업: {tasks_str}
        3. 현재 서버 역할: {server_roles}
        4. 관련 멤버: {members}

        [입력 대화]:
        {transcript}

        [출력 포맷 (JSON Only)]:
        {{
            "new_tasks": [
                {{"content": "게임 기획 초안 작성", "project": "게임개발", "assignee_hint": "김철수", "is_new_project": true, "suggested_parent": null}}
            ],
            "updates": [],
            "create_roles": ["기획자", "개발자"],
            "assign_roles": [{{"member_name": "김철수", "role_name": "기획자"}}]
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
            # JSON 파싱 실패 시 빈 딕셔너리가 아닌, 에러를 알릴 수 있는 더미 데이터라도 반환 고려 가능
            return {}
        except Exception as e:
            print(f"AI Error: {e}")
            return {}

    async def review_code(self, repo, author, msg, diff):
        if not self.model: return "❌ Key Missing"
        prompt = f"GitHub Review.\nRepo:{repo}, User:{author}, Msg:{msg}\nDiff:{diff[:20000]}\nKorean response."
        try: return (await asyncio.to_thread(self.model.generate_content, prompt)).text
        except: return "Error"