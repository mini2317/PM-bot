import aiohttp
from aiohttp import web
import discord
import re
import io
import asyncio
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
            web_url = c['url']
            cid_short = c['id'][:7]
            
            # Task 자동 완료
            matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', message, re.IGNORECASE)
            closed = []
            for t in matches:
                if self.bot.db.update_task_status(int(t), "DONE"): closed.append(t)
            
            msg_head = f"🚀 **Push** `{rn}`\nCommit: [`{cid_short}`]({web_url})\nMsg: `{message}`"
            if closed: msg_head += f"\n✅ Closed: {', '.join(closed)}"
            
            diff = await self.get_github_diff(f"https://api.github.com/repos/{rn}/commits/{c['id']}")
            pdf_bytes = None
            review_embeds = []
            
            if diff and len(diff.strip()) > 0:
                # [UPDATE] JSON 데이터 수신
                review_json = await self.bot.ai.review_code(rn, author, message, diff)
                
                # 1. PDF 생성 (JSON 전달)
                pdf_title = f"Code Review: {rn} ({cid_short})"
                pdf_buffer = await asyncio.to_thread(generate_review_pdf, pdf_title, review_json, web_url)
                pdf_bytes = pdf_buffer.getvalue()
                
                # 2. Embed 생성 (JSON 데이터를 마크다운으로 예쁘게 변환)
                summary = review_json.get('summary', '요약 없음')
                score = review_json.get('score', 0)
                issues = review_json.get('issues', [])
                suggestions = review_json.get('suggestions', [])

                # 메인 Embed (요약 및 점수)
                color = discord.Color.green() if score >= 80 else discord.Color.orange() if score >= 50 else discord.Color.red()
                main_embed = discord.Embed(title=f"🤖 AI Code Review (Score: {score})", url=web_url, color=color, description=summary)
                
                # 이슈 목록 (상위 3개만 표시, 나머지는 PDF 유도)
                if issues:
                    issue_text = ""
                    for issue in issues[:3]:
                        icon = "🔴" if issue.get('severity') == '상' else "🟡" if issue.get('severity') == '중' else "🟢"
                        issue_text += f"{icon} **[{issue.get('type')}]** {issue.get('description')}\n"
                    
                    if len(issues) > 3:
                        issue_text += f"...외 {len(issues)-3}건 (PDF 참조)"
                    main_embed.add_field(name="🚨 주요 이슈", value=issue_text, inline=False)
                
                # 제안 사항 (상위 2개만)
                if suggestions:
                    sug_text = "\n".join([f"💡 {s}" for s in suggestions[:2]])
                    if len(suggestions) > 2: sug_text += "\n..."
                    main_embed.add_field(name="✨ 개선 제안", value=sug_text, inline=False)
                
                main_embed.set_footer(text="상세 리포트는 첨부된 PDF 파일을 확인하세요.")
                review_embeds.append(main_embed)

            # 전송
            for cid in cids:
                ch = self.bot.get_channel(cid)
                if ch:
                    try:
                        if review_embeds:
                            f_send = discord.File(io.BytesIO(pdf_bytes), filename=f"Review_{cid_short}.pdf")
                            await ch.send(content=msg_head, embed=review_embeds[0], file=f_send)
                        else:
                            await ch.send(content=msg_head)
                            if diff is None:
                                await ch.send(embed=discord.Embed(title="⚠️ 분석 생략", description="변경량이 너무 많아 분석하지 못했습니다.", color=discord.Color.greyple()))
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