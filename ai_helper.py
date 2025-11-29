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
        """회의록 텍스트 요약 및 제목 생성"""
        if not self.model: return "제목: 알 수 없음\n\nAPI 키가 없습니다."

        prompt = f"""
        [대화 스크립트]:
        {transcript}

        위 내용을 분석해서 **가장 적절한 '회의 제목'**과 **'회의록'**을 작성해줘.
        첫 줄은 반드시 "제목: [AI가 추천하는 제목]" 형식이어야 해.
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except Exception as e:
            return f"제목: 에러 발생\n\n{e}"

    async def extract_tasks_and_updates(self, transcript, existing_projects, active_tasks):
        """
        [NEW] 할 일 추출 및 상태 변경 감지 통합 함수
        - transcript: 회의 대화 내용
        - existing_projects: 현재 존재하는 프로젝트 이름 리스트
        - active_tasks: 현재 진행 중인 태스크 리스트 [{'id', 'content', 'status'}]
        """
        if not self.model: return {"new_tasks": [], "updates": []}

        # 컨텍스트 정보 문자열 변환
        projects_str = ", ".join(existing_projects) if existing_projects else "(없음)"
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)

        prompt = f"""
        당신은 프로젝트 매니저입니다. 회의 대화 내용을 분석하여 다음 두 가지를 수행하세요.

        1. **새로운 할 일(New Tasks) 추출**:
           - 대화에서 도출된 액션 아이템을 뽑아주세요.
           - `project`: 기존 프로젝트 목록({projects_str}) 중 가장 적절한 것을 고르세요.
           - 만약 기존 프로젝트에 어울리는 게 없다면, **새로운 프로젝트 이름**을 제안하세요.
           - `assignee_hint`: 담당자가 언급되었다면 이름을 적으세요.

        2. **상태 변경(Updates) 감지**:
           - 기존 할 일 목록({tasks_str})을 참고하여, 회의 중 완료되었거나 상태가 바뀐 업무가 있다면 찾으세요.
           - 예: "로그인 기능 다 했어요" -> ID X번 Task Status 'DONE' 제안.

        [대화 내용]:
        {transcript}

        [출력 형식]: 반드시 아래 **JSON 포맷**으로만 출력하세요. (마크다운 없이)
        {{
            "new_tasks": [
                {{"content": "할 일 내용", "project": "프로젝트명", "assignee_hint": "이름", "is_new_project": true/false}}
            ],
            "updates": [
                {{"task_id": 123, "status": "DONE", "reason": "회의 중 완료 언급됨"}}
            ]
        }}
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            text = response.text
            # JSON 파싱 (```json 제거 등)
            text = re.sub(r'```json\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = text.strip()
            return json.loads(text)
        except Exception as e:
            print(f"AI Extraction Error: {e}")
            return {"new_tasks": [], "updates": []}

    async def review_code(self, repo, author, msg, diff):
        # (기존 코드와 동일)
        if not self.model: return "❌ API Key Missing"
        prompt = f"GitHub Review.\nRepo:{repo}, User:{author}, Msg:{msg}\nDiff:{diff[:15000]}\nKorean response."
        try:
            return (await asyncio.to_thread(self.model.generate_content, prompt)).text
        except: return "Error"