import json

class ContextManager:
    def __init__(self, db):
        self.db = db

    def build_guild_context(self, guild_id):
        """
        서버의 모든 프로젝트, 할 일, 구조 정보를 하나의 구조화된 텍스트로 생성합니다.
        마치 지식 그래프를 텍스트로 풀어쓴 것과 같은 효과를 냅니다.
        """
        # 1. 프로젝트 트리 조회
        proj_rows = self.db.get_project_tree(guild_id) # [(id, name, parent_id), ...]
        
        # 2. 할 일 조회 (완료되지 않은 것만)
        tasks = self.db.get_active_tasks_simple(guild_id) # [{'id', 'content', 'status', 'project_id'??}]
        # 참고: get_active_tasks_simple이 project_id도 반환하도록 DB 메서드 수정 필요할 수 있음
        # 여기서는 편의상 tasks를 다시 조회한다고 가정하거나, 기존 메서드를 활용
        
        # 데이터 구조화
        project_map = {r[0]: {'name': r[1], 'parent': r[2], 'tasks': [], 'children': []} for r in proj_rows}
        project_map[0] = {'name': '미분류(Inbox)', 'parent': None, 'tasks': [], 'children': []} # ID 0 or None for No Project

        # 할 일 매핑 (이 로직을 위해 tasks 테이블 조회 시 project_id가 필요함)
        # 현재 get_active_tasks_simple은 project_id를 안 가져오므로,
        # 아래 로직을 위해 DB 쿼리를 조금 수정하거나 여기서 전체 조회를 다시 해야 함.
        # (성능 최적화를 위해선 DB 쿼리 수정 권장. 여기선 개념적으로 설명)
        
        all_tasks_detail = self.db.get_tasks(guild_id) 
        # get_tasks 리턴: (task_id, proj_name, content, assignee_id, assignee_name, status)
        
        for t in all_tasks_detail:
            tid, pname, content, aid, aname, status = t
            # 프로젝트 이름으로 매핑 (ID가 더 정확하지만 현재 구조상 이름 사용)
            # 편의상 텍스트로 바로 구성
            task_str = f"- [#{tid}] {content} (담당: {aname or '미정'}) [{status}]"
            
            # 해당 프로젝트 찾기 (이름 매칭)
            found = False
            for pid, pdata in project_map.items():
                if pdata['name'] == pname:
                    pdata['tasks'].append(task_str)
                    found = True
                    break
            if not found:
                project_map[0]['tasks'].append(task_str)

        # 트리 구조 형성
        root_projects = []
        for pid, pdata in project_map.items():
            if pid == 0: continue
            if pdata['parent'] and pdata['parent'] in project_map:
                project_map[pdata['parent']]['children'].append(pdata)
            else:
                root_projects.append(pdata)

        # 3. 텍스트 렌더링 (재귀)
        def render_project(proj, level=0):
            indent = "  " * level
            output = f"{indent}📁 **{proj['name']}**\n"
            
            # 할 일 출력
            for t in proj['tasks']:
                output += f"{indent}  └ {t}\n"
            
            # 하위 프로젝트 출력
            for child in proj['children']:
                output += render_project(child, level + 1)
            return output

        context_text = "=== [현재 프로젝트 및 업무 현황] ===\n"
        for proj in root_projects:
            context_text += render_project(proj)
        
        # 미분류 항목
        if project_map[0]['tasks']:
            context_text += "📁 **미분류 작업**\n"
            for t in project_map[0]['tasks']:
                context_text += f"  └ {t}\n"

        return context_text