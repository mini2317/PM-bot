import discord
import json
import io
import asyncio
from services.pdf import generate_meeting_pdf
from ui import MeetingTaskView, RoleAssignmentView, RoleCreationView, NewProjectView, StatusUpdateView

async def process_meeting_result(ctx, bot, data, raw_messages):
    """
    회의 종료 후 데이터를 분석하고 결과를 처리하는 핵심 로직
    """
    start_msg_id = data.get('start_msg_id')
    project_name = data.get('project_name', '일반')
    
    # 1. 화자 익명화
    txt, user_map, reverse_map = _anonymize_transcript(raw_messages)
    
    # AI 언어 혼용 방지 시스템 메시지
    system_note = (
        "[System Instruction]\n"
        "1. **반드시 한국어로만 작성하세요.**\n"
        "2. 화자는 `{Speaker X}` 형식을 그대로 유지하세요.\n"
        "--------------------------------------------------\n"
    )
    final_transcript = system_note + txt
    
    waiting = await ctx.send("🤖 AI 분석 및 정리 중... (화자 익명화 적용)")

    # 2. AI 요약
    full_result = await bot.ai.generate_meeting_summary(final_transcript)
    if not isinstance(full_result, dict):
        full_result = {"title": data['name'], "summary": str(full_result), "agenda": [], "decisions": []}

    # 결과 복원 (익명 -> 실명)
    _restore_names_in_json(full_result, reverse_map)

    # 날짜 유효성 검사 및 보정
    import datetime
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    date_str = full_result.get('date', today_str)
    if len(date_str) != 10 or not date_str[0].isdigit():
        full_result['date'] = today_str

    title = full_result.get('title', data['name'])
    summary_text = full_result.get('summary', '요약 없음')
    
    # 3. DB 저장
    summary_dump = json.dumps(full_result, ensure_ascii=False)
    m_id = bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary_dump, data['jump_url'])

    # 4. 파일 생성 (PDF는 제거됨, JSON만 생성)
    files_to_send = await _create_result_files(full_result, m_id)

    # 5. 할 일 분석
    # [UPDATE] 멤버 목록 생성
    mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])
    active = bot.db.get_active_tasks_simple(ctx.guild.id)
    
    # [UPDATE] 인자 4개 전달 (transcript, project_name, active_tasks, members)
    res = await bot.ai.extract_tasks_and_updates(final_transcript, project_name, active, mems)
    
    await waiting.delete()

    # 6. 데이터 복원 (할 일)
    new_tasks = _restore_tasks(res.get('new_tasks', []), project_name, reverse_map)
    # 역할/업데이트 관련은 비서 기능 제거로 인해 사용되지 않을 수 있으나, AI가 반환한다면 복원
    updates = res.get('updates', [])

    # 7. 포럼 게시글 본문 수정
    embed = discord.Embed(title=f"✅ {title}", description=summary_text[:3500], color=0x2ecc71)
    if full_result.get('decisions'):
        d_txt = "\n".join([f"• {d}" for d in full_result['decisions']])
        embed.add_field(name="☑ 결정 사항", value=d_txt[:1000], inline=False)
    embed.set_footer(text=f"Meeting ID: #{m_id} | 데이터(JSON) 첨부됨")

    await _update_forum_post(ctx, start_msg_id, embed, files_to_send)

    # 8. 스레드 닫기 함수
    async def close_thread_logic():
        try:
            new_thread_name = f"✅ {title}"
            if isinstance(ctx.channel.parent, discord.ForumChannel):
                done_tag = next((t for t in ctx.channel.parent.available_tags if t.name == "종료"), None)
                tags = [done_tag] if done_tag else []
                await ctx.channel.edit(name=new_thread_name, applied_tags=tags, archived=True, locked=False)
            else:
                await ctx.channel.edit(name=new_thread_name, archived=True, locked=False)
            
            proj_cog = bot.get_cog('ProjectCog')
            if proj_cog: await proj_cog.refresh_dashboard(ctx.guild.id)
        except Exception as e:
            print(f"스레드 닫기 실패: {e}")

    # 9. 할 일 등록 절차
    if new_tasks:
        view = MeetingTaskView(new_tasks, m_id, ctx.author, ctx.guild, bot.db, cleanup_callback=close_thread_logic)
        await ctx.send("📝 **회의에서 도출된 할 일들을 등록할까요?**", view=view)
    else:
        await ctx.send("💡 추가된 할 일이 없습니다.")
        await close_thread_logic()

# --- 내부 헬퍼 함수들 ---

def _anonymize_transcript(raw_messages):
    user_map = {} 
    reverse_map = {} 
    speaker_idx = 1
    anon_transcript = ""
    
    for msg in raw_messages:
        real_name = msg['user']
        if real_name not in user_map:
            anon_name = f"{{Speaker {chr(64 + speaker_idx)}}}" if speaker_idx <= 26 else f"{{Speaker {speaker_idx}}}"
            user_map[real_name] = anon_name
            reverse_map[anon_name] = real_name
            speaker_idx += 1
        anon_transcript += f"[{user_map[real_name]} | {msg['time']}] {msg['content']}\n"
        
    return anon_transcript, user_map, reverse_map

def _restore_text(text, reverse_map):
    if not text: return ""
    sorted_keys = sorted(reverse_map.keys(), key=len, reverse=True)
    for anon in sorted_keys:
        if anon in text:
            text = text.replace(anon, reverse_map[anon])
    return text

def _restore_names_in_json(data, reverse_map):
    if 'title' in data:
        data['title'] = _restore_text(data['title'], reverse_map)
    data['summary'] = _restore_text(data.get('summary', ''), reverse_map)
    data['decisions'] = [_restore_text(d, reverse_map) for d in data.get('decisions', [])]
    for item in data.get('agenda', []):
        item['topic'] = _restore_text(item.get('topic', ''), reverse_map)
        item['content'] = _restore_text(item.get('content', ''), reverse_map)

async def _create_result_files(full_result, m_id):
    files = []
    # PDF 제거됨
    try:
        json_bytes = json.dumps(full_result, ensure_ascii=False, indent=2).encode('utf-8')
        files.append(discord.File(io.BytesIO(json_bytes), filename=f"Meeting_{m_id}_context.json"))
    except: pass
    return files

def _restore_tasks(tasks, project_name, reverse_map):
    restored = []
    for t in tasks:
        content = _restore_text(t.get('content', ''), reverse_map)
        anon_assignee = t.get('assignee_hint', '')
        real_assignee = _restore_text(anon_assignee, reverse_map)
        
        restored.append({
            'content': content,
            'project': project_name, 
            'assignee_hint': real_assignee 
        })
    return restored

async def _update_forum_post(ctx, start_msg_id, embed, files):
    msg_edited = False
    if start_msg_id:
        try:
            start_msg = await ctx.channel.fetch_message(start_msg_id)
            for f in files: f.fp.seek(0)
            await start_msg.edit(content="🏁 **회의 종료됨**", embed=embed, attachments=files)
            msg_edited = True
        except Exception as err:
            print(f"본문 수정 실패: {err}")
    
    if not msg_edited:
        for f in files: f.fp.seek(0)
        await ctx.send(embed=embed, files=files)