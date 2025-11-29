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

        prompt = f"""
        당신은 유능한 프로젝트 매니저입니다. 아래 회의 내용을 바탕으로 핵심을 요약하세요.
        
        [지시사항]
        1. **반드시 한국어로 작성하세요.**
        2. 첫 줄은 "제목: [회의 내용을 관통하는 제목]" 형식으로 작성하세요.
        3. 단순 나열보다는 논의의 흐름(문제제기 -> 논의 -> 결정 -> 향후계획)이 보이도록 요약하세요.

        [대화 스크립트]:
        {transcript}
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text
        except Exception as e:
            return f"제목: 에러 발생\n\n{e}"

    async def extract_tasks_and_updates(self, transcript, project_structure_text, active_tasks):
        """
        [UPDATE] 소극적인 태스크 추출 방지 및 문맥 파악 강화
        """
        if not self.model: return {"new_tasks": [], "updates": []}

        tasks_str = json.dumps(active_tasks, ensure_ascii=False)

        prompt = f"""
        회의 대화 내용을 분석하여 프로젝트 관리 정보를 JSON으로 추출하세요.
        
        [매우 중요 지시사항 - 할 일 추출 기준]
        **"할 일 없음"이라고 쉽게 결론 내리지 마세요.**
        대화 내용을 깊이 분석하여 아래와 같은 뉘앙스도 모두 **새로운 할 일(new_tasks)**로 잡으세요:
        1. **미래형 발언**: "~해야겠다", "~할 예정이다", "~하기로 하자"
        2. **제안 및 필요성**: "~가 필요해 보인다", "~는 고쳐야 한다", "다음엔 ~를 해보자"
        3. **담당자가 불명확해도**: 누군가는 해야 할 일이라면 일단 추출하세요. (담당자 미정으로)
        4. **아이디어 단계**: 구체적이지 않아도 "기획", "조사" 등의 태스크로 구체화하세요.

        [컨텍스트 정보]
        1. 현재 프로젝트 구조:
        {project_structure_text}
        (새 할 일이 기존 프로젝트의 하위인지, 아예 새로운 프로젝트가 필요한지 판단하세요.)

        2. 진행 중인 작업:
        {tasks_str}

        [출력 데이터 구조]
        1. **new_tasks**: 
           - `content`: 할 일 내용 (동사형으로 끝맺음, 예: "UI 수정하기")
           - `project`: 기존 프로젝트명 또는 새 프로젝트명
           - `is_new_project`: 새 프로젝트면 true
           - `suggested_parent`: 새 프로젝트일 경우 상위 프로젝트명 (없으면 null)
           - `assignee_hint`: 문맥상 추정되는 담당자 이름 (없으면 빈 문자열)
        
        2. **updates**: 
           - 대화 중 명시적으로 완료되었거나 상태가 바뀐 작업의 `task_id`와 `status`(TODO, IN_PROGRESS, DONE)

        [입력 대화]:
        {transcript}

        [출력 JSON 예시]:
        {{
            "new_tasks": [
                {{"content": "메인 페이지 배너 시안 제작", "project": "디자인", "assignee_hint": "김철수", "is_new_project": false, "suggested_parent": null}}
            ],
            "updates": []
        }}
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            text = response.text
            text = re.sub(r'```json\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = text.strip()
            return json.loads(text)
        except Exception as e:
            print(f"AI Extraction Error: {e}")
            return {"new_tasks": [], "updates": []}

    async def review_code(self, repo, author, msg, diff):
        # (기존 동일)
        if not self.model: return "❌ API Key Missing"
        prompt = f"""
        GitHub 코드 리뷰.
        Repo:{repo}, User:{author}, Msg:{msg}
        Diff:{diff[:20000]}
        한국어로 1.목적 2.버그/위험 3.개선안 작성.
        """
        try:
            return (await asyncio.to_thread(self.model.generate_content, prompt)).text
        except: return "Error"