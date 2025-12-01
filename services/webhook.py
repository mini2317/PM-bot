import aiohttp
from aiohttp import web
import re
import io
import asyncio
# [변경] 인자 추가된 함수 임포트
from services.pdf import generate_review_pdf
from utils import smart_chunk_text
from ui import EmbedPaginator
import discord

class WebhookServer:
    def __init__(self, bot, port=8080, path="/github-webhook"):
        self.bot = bot
        self.port = port
        self.path = path
        self.app = web.Application()
        self.app.router.add_route('*', self.path, self.handler)

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        print(f"🌍 Webhook Server running on port {self.port}")

    async def get_github_diff(self, url):
        print(f"[DEBUG] Diff: {url}")
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self.bot.github_headers) as r:
                if r.status == 200:
                    d = await r.json()
                    lines = []
                    ignores = ['lock', '.png', '.jpg', '.svg', '.pdf']
                    for f in d.get('files', []):
                        fn = f['filename']
                        if any(x in fn for x in ignores):
                            lines.append(f"📄 {fn} (Skipped)")
                        elif not f.get('patch'):
                            lines.append(f"📄 {fn} (No Patch)")
                        else:
                            p = f['patch']
                            if len(p) > 2500: p = p[:2500] + "\n...(Truncated)"
                            lines.append(f"📄 {fn}\n{p}")
                    return "\n".join(lines)
        return None

    async def process_payload(self, data):
        if 'repository' not in data: return
        rn = data['repository']['full_name']
        cids = self.bot.db.get_repo_channels(rn)
        if not cids: return
        
        for c in data.get('commits', []):
            author = c['author']['name']
            message = c['message']
            web_url = c['url'] # [중요] 링크 URL
            cid_short = c['id'][:7]
            
            msg = f"🚀 `{rn}` Commit: [`{cid_short}`]({web_url})\n{message}"
            
            # Task 자동 완료
            matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', message, re.IGNORECASE)
            closed = []
            for t in matches:
                if self.bot.db.update_task_status(int(t), "DONE"): closed.append(t)
            if closed: msg += f"\n✅ Closed: {', '.join(closed)}"
            
            diff = await self.get_github_diff(f"[https://api.github.com/repos/](https://api.github.com/repos/){rn}/commits/{c['id']}")
            pdf_bytes = None
            review_embeds = []

            if diff and len(diff.strip()) > 0:
                review = await self.bot.ai.review_code(rn, author, message, diff)
                
                # [변경] PDF 생성 시 링크 전달
                pdf_title = f"Code Review: {rn} ({cid_short})"
                pdf_content = f"Author: {author}\nMessage: {message}\n\n{review}"
                
                pdf_buffer = await asyncio.to_thread(generate_review_pdf, pdf_title, pdf_content, web_url)
                pdf_bytes = pdf_buffer.getvalue()
                
                # Embed 청킹
                chunks = smart_chunk_text(review)
                for i, ch in enumerate(chunks):
                    e = discord.Embed(title="🤖 Review", description=ch, color=0x2ecc71)
                    e.set_footer(text=f"{i+1}/{len(chunks)}")
                    review_embeds.append(e)
            
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch:
                    try:
                        await ch.send(msg)
                        if review_embeds:
                            # 파일 객체는 전송 시마다 새로 생성 (스트림 닫힘 방지)
                            f_send = discord.File(io.BytesIO(pdf_bytes), filename=f"Review_{cid_short}.pdf")
                            
                            if len(review_embeds) > 1:
                                view = EmbedPaginator(review_embeds, author=None)
                                await ch.send(embed=review_embeds[0], view=view, file=f_send)
                            else:
                                await ch.send(embed=review_embeds[0], file=f_send)
                        elif diff is None:
                            await ch.send(embed=discord.Embed(title="⚠️ 분석 생략", description="변경량이 너무 많습니다.", color=0xe74c3c))
                    except Exception as e:
                        print(f"Err send {cid}: {e}")

    async def handler(self, request):
        if request.method == 'GET':
            return web.Response(text="🟢 Bot Webhook Server OK")
        try:
            data = await request.json()
            self.bot.loop.create_task(self.process_payload(data))
            return web.Response(text="OK")
        except Exception as e:
            print(f"Webhook Error: {e}")
            return web.Response(status=500)