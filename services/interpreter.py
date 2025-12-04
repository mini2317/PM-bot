import shlex
import discord
import asyncio
import datetime

class PynapseInterpreter:
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def execute(self, script, message):
        """
        PML 스크립트를 실행합니다.
        message: 디스코드 Message 객체 (Guild, Channel, Author 정보 포함)
        """
        results = []
        lines = script.strip().split('\n')
        guild = message.guild
        channel = message.channel
        author = message.author

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'): continue

            try:
                # shlex로 따옴표 안의 공백 보존 파싱
                parts = shlex.split(line)
                cmd = parts[0].upper()
                args = parts[1:]

                result = await self._dispatch(cmd, args, guild, channel, author)
                if result: results.append(f"✅ {result}")
            except Exception as e:
                results.append(f"❌ 실행 실패 ('{cmd}'): {e}")

        return "\n".join(results)

    async def _dispatch(self, cmd, args, guild, channel, author):
        # 1. MKPROJ "이름" (Make Project)
        if cmd == "MKPROJ":
            if len(args) < 1: raise ValueError("이름 필요")
            if self.db.create_project(guild.id, args[0]):
                return f"프로젝트 **{args[0]}** 생성"
            return f"프로젝트 **{args[0]}** 이미 존재"

        # 2. SETPAR "자식" "부모" (Set Parent)
        elif cmd == "SETPAR":
            if len(args) < 2: raise ValueError("자식, 부모 필요")
            if self.db.set_parent_project(guild.id, args[0], args[1]):
                return f"구조: **{args[0]}** ⊂ **{args[1]}**"
            raise ValueError("프로젝트 미발견")

        # 3. MKTASK "프로젝트" "내용" (Make Task)
        elif cmd == "MKTASK":
            if len(args) < 2: raise ValueError("프로젝트, 내용 필요")
            tid = self.db.add_task(guild.id, args[0], args[1])
            return f"할일 등록 (#{tid}): {args[1]}"

        # 4. DONE "ID" (Complete Task)
        elif cmd == "DONE":
            if len(args) < 1: raise ValueError("ID 필요")
            tid = int(args[0].replace('#', ''))
            if self.db.update_task_status(tid, "DONE"):
                return f"작업 #{tid} 완료"
            raise ValueError("작업 ID 없음")

        # 5. ASSIGN "ID" "멤버" (Assign Task)
        elif cmd == "ASSIGN":
            if len(args) < 2: raise ValueError("ID, 멤버 필요")
            tid = int(args[0].replace('#', ''))
            m_name = args[1]
            target = discord.utils.find(lambda m: m_name in m.display_name or m_name in m.name, guild.members)
            if not target: raise ValueError(f"멤버 '{m_name}' 미발견")
            
            if self.db.assign_task(tid, target.id, target.display_name):
                return f"담당 배정: #{tid} → {target.display_name}"
            raise ValueError("DB 에러")

        # 6. STAT "프로젝트(옵션)" (Status)
        elif cmd == "STAT":
            p_name = args[0] if args else None
            ts = self.db.get_tasks(guild.id, p_name)
            if not ts: return f"📭 '{p_name or '전체'}' 할일 없음"
            
            cnt = {'TODO':0, 'IN_PROGRESS':0, 'DONE':0}
            for t in ts:
                st = t[5] # status index
                if st in cnt: cnt[st]+=1
            return f"📊 '{p_name or '전체'}' 현황: 대기({cnt['TODO']}) 진행({cnt['IN_PROGRESS']}) 완료({cnt['DONE']})"

        # 7. MKREPO "Repo" (Make Repo)
        elif cmd == "MKREPO":
            if len(args) < 1: raise ValueError("레포명 필요")
            if self.db.add_repo(args[0], channel.id, author.name):
                return f"깃헙 연결: {args[0]}"
            raise ValueError("등록 실패")

        # 8. RMREPO "Repo" (Remove Repo)
        elif cmd == "RMREPO":
            if self.db.remove_repo(args[0], channel.id):
                return f"깃헙 해제: {args[0]}"
            raise ValueError("미등록 레포")

        # 9. MKMEET "제목" (Make Meeting)
        elif cmd == "MKMEET":
            mc = self.bot.get_cog('MeetingCog')
            if not mc: raise ValueError("회의 기능 로드 안됨")
            if channel.id in mc.meeting_buffer: raise ValueError("이미 회의 중")
            
            name = args[0] if args else f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
            try:
                th = await channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
                mc.meeting_buffer[th.id] = {'name': name, 'messages': [], 'jump_url': th.jump_url}
                await th.send("🔴 기록 시작")
                return f"회의 스레드 생성: {th.mention}"
            except Exception as e:
                raise ValueError(f"스레드 생성 실패: {e}")

        # 10. RMMEET ID (Remove Meeting)
        elif cmd == "RMMEET":
             if self.db.delete_meeting(int(args[0]), guild.id):
                 return f"회의록 #{args[0]} 삭제"
             raise ValueError("삭제 실패")

        # 11. SAY "메시지" / ASK "질문" (Handled by AssistantCog parsing, but here for no-op)
        elif cmd in ["SAY", "ASK"]:
            return None # 실행 로그에 남기지 않음

        else:
            raise ValueError(f"알 수 없는 명령: {cmd}")