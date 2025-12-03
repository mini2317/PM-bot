# ... (import, init, generate_content 등 기존 코드 유지) ...
# 편의를 위해 analyze_assistant_input 메서드만 수정해서 보여드립니다.

    async def analyze_assistant_input(self, chat_context, active_tasks, projects, guild_id):
        """
        [UPDATE] Gatekeeper 제거 (멘션 시 무조건 실행)
        RAG(기억) + 최근 대화(Context)를 조합하여 의도 파악
        """
        tasks_str = json.dumps(active_tasks, ensure_ascii=False)
        projs_str = ", ".join(projects) if projects else "없음"
        
        if isinstance(chat_context, list):
            query_text = chat_context[-1] # 가장 최근 메시지를 쿼리로 사용
            context_msg = "\n".join(chat_context)
        else:
            query_text = chat_context
            context_msg = str(chat_context)

        # [Gatekeeper Removed] 사용자가 호출했으므로 무조건 분석 진행

        # 1. RAG 검색
        relevant_memories = self.memory.query_relevant(query_text, guild_id)
        memory_context = "\n".join([f"- {m}" for m in relevant_memories]) if relevant_memories else "없음"

        # 2. 프롬프트 구성
        template = self.prompts.get('assistant_analysis', "")
        augmented_msg = f"[최근 대화 흐름]:\n{context_msg}\n\n[관련된 과거 기억]:\n{memory_context}"

        prompt = template.format(
            projs_str=projs_str,
            tasks_str=tasks_str,
            user_msg=augmented_msg 
        )

        logger.info(f"Analyzing Input (Direct Mention)...")
        try:
            res = await self.generate_content(prompt, is_json=True)
            
            res_clean = re.sub(r'```json\s*', '', res, flags=re.I)
            res_clean = re.sub(r'```\s*', '', res_clean)
            parsed_res = json.loads(res_clean.strip())
            
            if isinstance(parsed_res, list):
                parsed_res = parsed_res[0] if parsed_res else {}
            
            logger.info(f"Assistant Action: {parsed_res.get('action')}")
            return parsed_res
            
        except Exception as e:
            logger.error(f"Assistant Analysis Failed: {e}")
            return {"action": "none", "comment": "죄송합니다, 이해하지 못했습니다."}