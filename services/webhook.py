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
        
        self.bot_repo = None
        if hasattr(bot.ai, 'config'):
            self.bot_repo = bot.ai.config.get('bot_repo')

    def _get_github_token(self):
        try:
            with open("src/key/github_key", "r", encoding="utf-8") as f:
                return f.read().strip()
        except:
            return None

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        print(f"🌍 Webhook Server running on port {self.port}")

    async def _run_cmd(self, cmd):
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
        if 'repository' not in data: return
        rn = data['repository']['full_name']
        
        cids = self.bot.db.get_repo_channels(rn)
        is_self_update = (self.bot_repo and rn == self.bot_repo)
        
        if not cids and not is_self_update:
            print(f"[DEBUG] No channels found for repo: {rn}")
            return

        # 1. 리뷰 및 알림 로직
        commits = data.get('commits', [])
        for c in commits:
            author = c['author']['name']
            message = c['message']
            web_url = c['url']
            commit_id = c['id']
            short_id = commit_id[:7]

            matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', message, re.IGNORECASE)
            closed_tasks = []
            for t_id in matches:
                if self.bot.db.update_task_status(int(t_id), "DONE"):
                    closed_tasks.append(t_id)

            msg_head = f"🚀 **Push** `{rn}`\nCommit: [`{short_id}`]({web_url}) by **{author}**\nMsg: `{message}`"
            if closed_tasks:
                msg_head += f"\n✅ Closed: {', '.join(closed_tasks)}"
            
            api_url = f"https://api.github.com/repos/{rn}/commits/{commit_id}"
            diff_text = await self.get_github_diff(api_url)
            
            review_embeds = []
            pdf_bytes = None

            if diff_text and len(diff_text.strip()) > 0:
                review_json = await self.bot.ai.review_code(rn, author, message, diff_text)
                if isinstance(review_json, list): review_json = review_json[0] if review_json else {}

                pdf_title = f"Code Review: {rn} ({short_id})"
                pdf_buffer = await asyncio.to_thread(generate_review_pdf, pdf_title, review_json, web_url)
                pdf_bytes = pdf_buffer.getvalue()
                
                score = review_json.get('score', 0)
                summ = review_json.get('summary', '요약 없음')
                color = discord.Color.green() if score >= 80 else discord.Color.orange() if score >= 50 else discord.Color.red()
                
                main_embed = discord.Embed(title=f"🤖 AI Code Review (Score: {score})", url=web_url, color=color, description=summ)
                
                issues = review_json.get('issues', [])
                if issues:
                    i_txt = ""
                    for i in issues[:3]:
                        # [Fix] 이슈가 딕셔너리가 아닌 경우 처리
                        if isinstance(i, dict):
                            severity = i.get('severity', '중')
                            i_type = i.get('type', '알림')
                            desc = i.get('description', '')
                        else:
                            severity = '중'
                            i_type = '알림'
                            desc = str(i)

                        icon = "🔴" if severity == '상' else "🟡" if severity == '중' else "🟢"
                        i_txt += f"{icon} **[{i_type}]** {desc}\n"
                        
                    if len(issues) > 3: i_txt += f"...외 {len(issues)-3}건"
                    main_embed.add_field(name="🚨 이슈", value=i_txt, inline=False)
                
                main_embed.set_footer(text="상세 내용은 PDF 참조")
                review_embeds.append(main_embed)

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

        # 2. 강제 업데이트 로직
        if is_self_update:
            print(f"🔄 Self-update triggered for {rn}")
            
            notify_channels = []
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch:
                    notify_channels.append(ch)
                    try: await ch.send("🔄 **봇 업데이트 진행 중...**")
                    except: pass
            
            token = self._get_github_token()
            remote_url = f"https://{token}@github.com/{rn}.git" if token else "origin"
            
            try:
                code, out, err = await self._run_cmd(f"git fetch {remote_url}")
                if code != 0:
                    print(f"❌ Fetch Failed: {err}")
                    for ch in notify_channels: await ch.send(f"⚠️ 업데이트 실패 (Fetch): {err[:200]}")
                    return

                code, out, err = await self._run_cmd("git reset --hard FETCH_HEAD")
                if code != 0:
                    print(f"❌ Reset Failed: {err}")
                    for ch in notify_channels: await ch.send(f"⚠️ 업데이트 실패 (Reset): {err[:200]}")
                    return
                
                print(f"✅ Code Forced Updated: {out}")

                await self._run_cmd(f"{sys.executable} -m pip install -r requirements.txt")
                
                print("♻️ Restarting bot...")
                sys.exit(0)
                
            except Exception as e:
                print(f"❌ Update Error: {e}")
                for ch in notify_channels: await ch.send(f"⚠️ 업데이트 에러: {str(e)[:200]}")

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