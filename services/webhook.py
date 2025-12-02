import sys
import types

# [Patch] Python 3.13+ compatibility: Mock audioop if missing
# 'audioop' was removed in Python 3.13, which causes crashes in libraries like discord.py
# that attempt to import it for voice support. This mock prevents the ImportError.
if sys.version_info >= (3, 13):
    try:
        import audioop
    except ImportError:
        mock_audioop = types.ModuleType("audioop")
        class error(Exception): pass
        mock_audioop.error = error
        # Inject into sys.modules so subsequent imports find it
        sys.modules["audioop"] = mock_audioop

import aiohttp
from aiohttp import web
import discord
import re
import io
import asyncio
import subprocess
import sys
import json
from services.pdf import generate_review_pdf
from utils import smart_chunk_text
from ui import EmbedPaginator

class WebhookServer:
    def __init__(self, bot, port=8080, path="/github-webhook"):
        self.bot = bot
        self.port = port
        self.path = path
        self.app = web.Application()
        self.app.router.add_route('*', self.path, self.handler)
        
        # config에서 봇 자신의 레포지토리 정보 로드 (자동 업데이트용)
        self.bot_repo = None
        if hasattr(bot.ai, 'config'):
            self.bot_repo = bot.ai.config.get('bot_repo')

    async def start(self):
        """웹 서버를 비동기로 시작합니다."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        print(f"🌍 Webhook Server running on port {self.port}")

    async def get_github_diff(self, url):
        """
        Github API를 통해 커밋의 Diff를 가져옵니다.
        너무 큰 파일이나 불필요한 파일(lock, 이미지 등)은 제외합니다.
        """
        print(f"[DEBUG] Diff Request: {url}")
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self.bot.github_headers) as r:
                if r.status == 200:
                    d = await r.json()
                    lines = []
                    
                    # 분석에서 제외할 파일명 및 확장자
                    ignored_files = ['package-lock.json', 'yarn.lock', 'poetry.lock', 'Gemfile.lock']
                    ignored_exts = ('.svg', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.woff', '.ttf')

                    for f in d.get('files', []):
                        fn = f['filename']
                        
                        # 1. 노이즈 필터링
                        if any(x in fn for x in ignored_files) or fn.endswith(ignored_exts):
                            lines.append(f"📄 {fn} (Skipped: Auto-generated/Asset)")
                            continue

                        # 2. Patch 유무 확인
                        patch = f.get('patch', None)
                        if not patch:
                            lines.append(f"📄 {fn} (Skipped: Binary or Too Large)")
                            continue
                        
                        # 3. 길이 제한 (파일당 2500자)
                        if len(patch) > 2500:
                            patch = patch[:2500] + "\n... (Diff truncated due to length) ..."
                        
                        lines.append(f"📄 {fn}\n{patch}\n")
                    
                    return "\n".join(lines)
                else:
                    print(f"[DEBUG] Diff Fetch Error: Status {r.status}")
        return None

    async def process_payload(self, data):
        """웹훅 페이로드 처리 (자동 업데이트 및 일반 리뷰)"""
        if 'repository' not in data: return
        rn = data['repository']['full_name']
        
        # ---------------------------------------------------------
        # [기능 1] 봇 자동 업데이트 (Self-Update)
        # ---------------------------------------------------------
        if self.bot_repo and rn == self.bot_repo:
            print(f"🔄 Self-update triggered for {rn}")
            
            # 알림 전송
            cids = self.bot.db.get_repo_channels(rn)
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch: 
                    try: await ch.send("🔄 **봇 업데이트 감지!**\n최신 코드를 받아오고 재시작합니다... (잠시 후 복구됩니다)")
                    except: pass
            
            try:
                # 1. Git Pull
                process = await asyncio.create_subprocess_shell(
                    "git pull",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    print(f"✅ Git Pull Success: {stdout.decode()}")
                    
                    # 2. Pip Install (의존성 변경 대비)
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
                    
                    print("♻️ Restarting bot...")
                    # 3. 종료 (Systemd가 자동 재시작)
                    sys.exit(0) 
                else:
                    print(f"❌ Git Pull Failed: {stderr.decode()}")
            except Exception as e:
                print(f"❌ Update Error: {e}")

            # 업데이트 로직이 실행되면 일반 리뷰는 건너뜀
            return 

        # ---------------------------------------------------------
        # [기능 2] 일반 레포지토리 코드 리뷰 및 알림
        # ---------------------------------------------------------
        cids = self.bot.db.get_repo_channels(rn)
        if not cids: 
            print(f"[DEBUG] No channels found for repo: {rn}")
            return
        
        commits = data.get('commits', [])
        if not commits: return

        for c in commits:
            author = c['author']['name']
            message = c['message']
            web_url = c['url']
            commit_id = c['id']
            short_id = commit_id[:7]

            # 1. 할 일 자동 완료 체크 (Fix #12)
            matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', message, re.IGNORECASE)
            closed_tasks = []
            for t_id in matches:
                if self.bot.db.update_task_status(int(t_id), "DONE"):
                    closed_tasks.append(t_id)

            # 2. 알림 메시지 구성
            msg_head = f"🚀 **Push** `{rn}`\nCommit: [`{short_id}`]({web_url}) by **{author}**\nMsg: `{message}`"
            if closed_tasks:
                msg_head += f"\n✅ Closed: " + ", ".join([f"#{t}" for t in closed_tasks])
            
            # 3. Diff 가져오기 및 AI 리뷰 생성
            api_url = f"https://api.github.com/repos/{rn}/commits/{commit_id}"
            diff_text = await self.get_github_diff(api_url)
            
            review_embeds = []
            pdf_bytes = None

            if diff_text and len(diff_text.strip()) > 0:
                # AI 리뷰 요청 (JSON 응답)
                review_json = await self.bot.ai.review_code(rn, author, message, diff_text)
                
                # [Safety Fix] AI가 List로 반환할 경우 Dict로 보정
                if isinstance(review_json, list):
                    review_json = review_json[0] if review_json else {}

                # PDF 생성 (JSON 데이터 전달)
                pdf_title = f"Code Review: {rn} ({short_id})"
                
                # 비동기 PDF 생성 (I/O 블로킹 방지)
                pdf_buffer = await asyncio.to_thread(generate_review_pdf, pdf_title, review_json, web_url)
                pdf_bytes = pdf_buffer.getvalue()
                
                # Embed 생성 (요약본)
                score = review_json.get('score', 0)
                summary = review_json.get('summary', '요약 없음')
                
                # 점수에 따른 색상
                color = discord.Color.green() if score >= 80 else discord.Color.orange() if score >= 50 else discord.Color.red()
                
                main_embed = discord.Embed(title=f"🤖 AI Code Review (Score: {score})", url=web_url, color=color, description=summary)
                
                # 이슈 목록 (상위 3개만)
                issues = review_json.get('issues', [])
                if issues:
                    issue_text = ""
                    for issue in issues[:3]:
                        icon = "🔴" if issue.get('severity') == '상' else "🟡" if issue.get('severity') == '중' else "🟢"
                        issue_text += f"{icon} **[{issue.get('type')}]** {issue.get('description')}\n"
                    if len(issues) > 3: issue_text += f"...외 {len(issues)-3}건 (PDF 참조)"
                    main_embed.add_field(name="🚨 주요 이슈", value=issue_text, inline=False)
                
                # 제안 사항 (상위 2개만)
                suggestions = review_json.get('suggestions', [])
                if suggestions:
                    sug_text = "\n".join([f"💡 {s}" for s in suggestions[:2]])
                    if len(suggestions) > 2: sug_text += "\n..."
                    main_embed.add_field(name="✨ 개선 제안", value=sug_text, inline=False)

                main_embed.set_footer(text="상세 내용은 첨부된 PDF를 확인하세요.")
                review_embeds.append(main_embed)

            # 4. 각 채널로 전송
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch:
                    try:
                        # 파일 객체는 전송할 때마다 새로 생성해야 함 (스트림 포지션 문제 방지)
                        file_to_send = None
                        if pdf_bytes:
                            file_to_send = discord.File(io.BytesIO(pdf_bytes), filename=f"Review_{short_id}.pdf")
                        
                        if review_embeds:
                            await ch.send(content=msg_head, embed=review_embeds[0], file=file_to_send)
                        else:
                            # 리뷰가 없는 경우 (Diff 없음 등)
                            await ch.send(content=msg_head)
                            if diff_text is None:
                                await ch.send(embed=discord.Embed(title="⚠️ 분석 생략", description="변경량이 너무 많거나 분석할 코드가 없습니다.", color=discord.Color.light_grey()))
                    
                    except Exception as e:
                        print(f"[ERROR] Failed to send to channel {cid}: {e}")

    async def handler(self, request):
        """웹훅 요청 핸들러"""
        if request.method == 'GET':
            return web.Response(text="🟢 Bot Webhook Server OK")
        
        try:
            data = await request.json()
            # 백그라운드 태스크로 처리 (응답 속도 향상)
            self.bot.loop.create_task(self.process_payload(data))
            return web.Response(text="OK", status=200)
        except Exception as e:
            print(f"[ERROR] Webhook Handler Error: {e}")
            return web.Response(status=500)