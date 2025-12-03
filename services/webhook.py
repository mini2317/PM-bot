import sys
import types

# [Patch] Python 3.13+ compatibility: Mock audioop if missing
# 'audioop' was removed in Python 3.13, which causes crashes in libraries like discord.py
if sys.version_info >= (3, 13):
    try:
        import audioop
    except ImportError:
        mock_audioop = types.ModuleType("audioop")
        class error(Exception): pass
        mock_audioop.error = error
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
import os
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
        
        # config에서 봇 자신의 레포지토리 정보 로드
        self.bot_repo = None
        if hasattr(bot.ai, 'config'):
            self.bot_repo = bot.ai.config.get('bot_repo')

    def _get_github_token(self):
        """키 파일에서 Github 토큰 로드"""
        try:
            with open("src/key/github_key", "r", encoding="utf-8") as f:
                return f.read().strip()
        except:
            return None

    async def start(self):
        """웹 서버 시작"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        print(f"🌍 Webhook Server running on port {self.port}")

    async def _run_cmd(self, cmd):
        """쉘 명령어 비동기 실행 헬퍼"""
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return process.returncode, stdout.decode().strip(), stderr.decode().strip()
        except Exception as e:
            return -1, "", str(e)

    async def get_github_diff(self, url):
        """Github API로 Diff 가져오기 (노이즈 필터링 포함)"""
        print(f"[DEBUG] Diff Request: {url}")
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self.bot.github_headers) as r:
                if r.status == 200:
                    d = await r.json()
                    lines = []
                    
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
                        
                        # 3. 길이 제한
                        if len(patch) > 2500:
                            patch = patch[:2500] + "\n... (Diff truncated due to length) ..."
                        
                        lines.append(f"📄 {fn}\n{patch}\n")
                    
                    return "\n".join(lines)
                else:
                    print(f"[DEBUG] Diff Fetch Error: Status {r.status}")
        return None

    async def process_payload(self, data):
        """웹훅 페이로드 처리 (자동 업데이트 및 리뷰)"""
        if 'repository' not in data: return
        rn = data['repository']['full_name']
        
        # 채널 확인
        cids = self.bot.db.get_repo_channels(rn)
        
        # 봇 업데이트인지 확인
        is_self_update = (self.bot_repo and rn == self.bot_repo)
        
        if not cids and not is_self_update:
            print(f"[DEBUG] No channels found for repo: {rn}")
            return

        # 1. [공통] 커밋 리뷰 및 알림 전송
        commits = data.get('commits', [])
        for c in commits:
            author = c['author']['name']
            message = c['message']
            web_url = c['url']
            commit_id = c['id']
            short_id = commit_id[:7]

            # Task 자동 완료 체크
            matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', message, re.IGNORECASE)
            closed_tasks = []
            for t_id in matches:
                if self.bot.db.update_task_status(int(t_id), "DONE"):
                    closed_tasks.append(t_id)

            msg_head = f"🚀 **Push** `{rn}`\nCommit: [`{short_id}`]({web_url}) by **{author}**\nMsg: `{message}`"
            if closed_tasks:
                msg_head += f"\n✅ Closed: {', '.join(closed_tasks)}"
            
            # Diff & AI Review
            api_url = f"https://api.github.com/repos/{rn}/commits/{commit_id}"
            diff_text = await self.get_github_diff(api_url)
            
            review_embeds = []
            pdf_bytes = None

            if diff_text and len(diff_text.strip()) > 0:
                review_json = await self.bot.ai.review_code(rn, author, message, diff_text)
                
                if isinstance(review_json, list):
                    review_json = review_json[0] if review_json else {}

                # PDF 생성
                pdf_title = f"Code Review: {rn} ({short_id})"
                pdf_buffer = await asyncio.to_thread(generate_review_pdf, pdf_title, review_json, web_url)
                pdf_bytes = pdf_buffer.getvalue()
                
                # Embed 생성
                score = review_json.get('score', 0)
                summ = review_json.get('summary', '요약 없음')
                color = discord.Color.green() if score >= 80 else discord.Color.orange() if score >= 50 else discord.Color.red()
                
                main_embed = discord.Embed(title=f"🤖 AI Code Review (Score: {score})", url=web_url, color=color, description=summ)
                
                issues = review_json.get('issues', [])
                if issues:
                    i_txt = ""
                    for i in issues[:3]:
                        icon = "🔴" if i.get('severity')=='상' else "🟡"
                        i_txt += f"{icon} **[{i.get('type')}]** {i.get('description')}\n"
                    if len(issues)>3: i_txt += f"...외 {len(issues)-3}건"
                    main_embed.add_field(name="🚨 이슈", value=i_txt, inline=False)
                
                main_embed.set_footer(text="상세 내용은 PDF 참조")
                review_embeds.append(main_embed)

            # 채널 전송
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch:
                    try:
                        f_send = None
                        if pdf_bytes:
                            f_send = discord.File(io.BytesIO(pdf_bytes), filename=f"Review_{short_id}.pdf")
                        
                        if review_embeds:
                            await ch.send(content=msg_head, embed=review_embeds[0], file=f_send)
                        else:
                            await ch.send(content=msg_head)
                            if diff_text is None:
                                await ch.send(embed=discord.Embed(title="⚠️ 분석 생략", description="변경량 과다 또는 분석할 파일 없음", color=discord.Color.light_grey()))
                    except Exception as e:
                        print(f"[ERROR] Send fail {cid}: {e}")

        # 2. [UPDATE] 강제 업데이트 로직 (Hard Reset)
        # 서버의 로컬 변경사항을 무시하고 원격 저장소 상태로 강제 동기화
        if is_self_update:
            print(f"🔄 Self-update triggered for {rn}")
            
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch: 
                    try: await ch.send("🔄 **봇 업데이트 진행 중...** (강제 동기화 및 재시작)")
                    except: pass
            
            token = self._get_github_token()
            # 토큰이 있으면 URL에 포함
            remote_url = f"https://{token}@github.com/{rn}.git" if token else "origin"
            
            try:
                # 1. Fetch (최신 이력 가져오기)
                code, out, err = await self._run_cmd(f"git fetch {remote_url}")
                if code != 0:
                    print(f"❌ Fetch Failed: {err}")
                    return

                # 2. Reset Hard (로컬 변경사항 날리고 최신버전으로 덮어쓰기)
                # 주의: DB파일 등이 .gitignore에 없으면 날아감
                code, out, err = await self._run_cmd("git reset --hard FETCH_HEAD")
                if code != 0:
                    print(f"❌ Reset Failed: {err}")
                    return
                
                print(f"✅ Code Forced Updated: {out}")

                # 3. Pip Install (의존성 갱신)
                await self._run_cmd(f"{sys.executable} -m pip install -r requirements.txt")
                
                print("♻️ Restarting bot...")
                # 4. 종료 (Systemd가 자동 재시작)
                sys.exit(0)
                
            except Exception as e:
                print(f"❌ Update Error: {e}")

    async def handler(self, request):
        if request.method == 'GET':
            return web.Response(text="🟢 Bot Webhook Server OK")
        try:
            data = await request.json()
            self.bot.loop.create_task(self.process_payload(data))
            return web.Response(text="OK", status=200)
        except Exception as e:
            print(f"[ERROR] Webhook: {e}")
            return web.Response(status=500)