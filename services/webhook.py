import sys
import types

# [Patch] Python 3.13+ compatibility
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

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        print(f"🌍 Webhook Server running on port {self.port}")

    async def get_github_diff(self, url):
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
                        if any(x in fn for x in ignored_files) or fn.endswith(ignored_exts):
                            lines.append(f"📄 {fn} (Skipped: Auto-generated/Asset)")
                            continue
                        patch = f.get('patch', None)
                        if not patch:
                            lines.append(f"📄 {fn} (Skipped: Binary or Too Large)")
                            continue
                        if len(patch) > 2500:
                            patch = patch[:2500] + "\n... (Diff truncated due to length) ..."
                        lines.append(f"📄 {fn}\n{patch}\n")
                    
                    return "\n".join(lines)
                else:
                    print(f"[DEBUG] Diff Fetch Error: Status {r.status}")
        return None

    async def process_payload(self, data):
        """웹훅 페이로드 처리"""
        if 'repository' not in data: return
        rn = data['repository']['full_name']
        
        # 1. 알림을 보낼 채널 확인
        cids = self.bot.db.get_repo_channels(rn)
        
        # 봇 레포지토리인 경우, 채널 등록이 안 되어 있어도 업데이트는 수행해야 함
        # 단, 리뷰 알림은 채널이 있어야 가능하므로 체크
        is_self_update = (self.bot_repo and rn == self.bot_repo)
        
        if not cids and not is_self_update:
            print(f"[DEBUG] No channels found for repo: {rn}")
            return

        # 2. [공통] 커밋 리뷰 및 알림 전송 (봇 자신이라도 수행)
        commits = data.get('commits', [])
        for c in commits:
            author = c['author']['name']
            message = c['message']
            web_url = c['url']
            commit_id = c['id']
            short_id = commit_id[:7]

            # Task 자동 완료
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
                
                # List 예외 처리
                if isinstance(review_json, list):
                    review_json = review_json[0] if review_json else {}

                # PDF
                pdf_title = f"Code Review: {rn} ({short_id})"
                # PDF 생성을 위한 텍스트 변환 (JSON -> Text)
                summary = review_json.get('summary', '')
                pdf_content_text = f"Author: {author}\nMessage: {message}\n\nSummary: {summary}\n\n"
                
                for issue in review_json.get('issues', []):
                    pdf_content_text += f"[{issue.get('type')}] {issue.get('description')}\n"
                
                if review_json.get('suggestions'):
                    pdf_content_text += "\nSuggestions:\n"
                    for sug in review_json.get('suggestions', []):
                        pdf_content_text += f"- {sug}\n"

                # JSON 원본도 같이 넘겨주는 것이 좋지만, 현재 PDF 함수는 Text 기반이므로 변환해서 넘김
                # 만약 services/pdf.py가 JSON을 받도록 수정되었다면 review_json을 넘기면 됨.
                # 여기서는 호환성을 위해 텍스트로 변환하여 넘깁니다. (이전 답변에서 PDF 함수가 업데이트 되었으므로 JSON을 넘기는 로직으로 수정 가능)
                # [수정] generate_review_pdf가 JSON(dict)을 받도록 업데이트 되었으므로 그대로 전달
                pdf_buffer = await asyncio.to_thread(generate_review_pdf, pdf_title, review_json, web_url)
                pdf_bytes = pdf_buffer.getvalue()
                
                # Embed
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

            # Send
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
                                await ch.send(embed=discord.Embed(title="⚠️ 분석 생략", description="변경량 과다", color=discord.Color.light_grey()))
                    except Exception as e:
                        print(f"[ERROR] Send fail {cid}: {e}")

        # 3. [기능 1 수정] 봇 자동 업데이트 (리뷰 후 실행)
        if is_self_update:
            print(f"🔄 Self-update triggered for {rn}")
            
            # 재시작 알림
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch: 
                    try: await ch.send("🔄 **봇 업데이트 적용 중...** (잠시 후 재시작됩니다)")
                    except: pass
            
            try:
                # Git Pull
                process = await asyncio.create_subprocess_shell(
                    "git pull",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    print(f"✅ Git Pull Success: {stdout.decode()}")
                    
                    # Pip Install
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
                    
                    print("♻️ Restarting bot...")
                    sys.exit(0) 
                else:
                    print(f"❌ Git Pull Failed: {stderr.decode()}")
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