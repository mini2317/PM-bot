import io
import os
import re
import html
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT

def register_fonts():
    font_path = "src/fonts/Nanum_Gothic/NanumGothic-Regular.ttf"
    font_name = 'Helvetica'
    try:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
            font_name = 'NanumGothic'
        else: print(f"⚠️ 폰트 없음: {font_path}")
    except: pass
    return font_name

# ... (parse_markdown_to_flowables, generate_review_pdf 등 기존 함수 유지) ...
# 편의상 기존 코드를 유지하고 아래 함수를 추가하세요.

def generate_meeting_pdf(meeting_data):
    """
    회의록 JSON 데이터를 PDF로 변환합니다.
    meeting_data: {'title':, 'date':, 'summary':, 'agenda': [{topic, content}], 'decisions': []}
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    font_name = register_fonts()
    styles = getSampleStyleSheet()

    # 스타일
    style_title = ParagraphStyle('M_Title', parent=styles['Title'], fontName=font_name, fontSize=24, leading=30, spaceAfter=20, textColor=colors.darkblue)
    style_h1 = ParagraphStyle('M_H1', parent=styles['Heading1'], fontName=font_name, fontSize=16, leading=20, spaceBefore=15, spaceAfter=10, textColor=colors.black)
    style_normal = ParagraphStyle('M_Norm', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=16, spaceAfter=5)
    style_box = ParagraphStyle('M_Box', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=16, backColor=colors.whitesmoke, borderPadding=10, spaceAfter=10)

    story = []

    # 1. 제목 & 날짜
    title = meeting_data.get('title', '회의록')
    date = meeting_data.get('date', '-')
    story.append(Paragraph(f"<b>{html.escape(title)}</b>", style_title))
    story.append(Paragraph(f"📅 Date: {date}", style_normal))
    story.append(Spacer(1, 15))

    # 2. 요약 (박스 스타일)
    summary = meeting_data.get('summary', '')
    if summary:
        story.append(Paragraph("📌 Summary", style_h1))
        story.append(Paragraph(html.escape(summary), style_box))

    # 3. 안건 (Agenda)
    agenda = meeting_data.get('agenda', [])
    if agenda:
        story.append(Paragraph("📋 Agenda & Discussions", style_h1))
        for item in agenda:
            topic = item.get('topic', 'Topic')
            content = item.get('content', '')
            # 볼드체로 토픽 표시
            story.append(Paragraph(f"<b>• {html.escape(topic)}</b>", style_normal))
            # 내용은 들여쓰기
            p = Paragraph(html.escape(content), style_normal)
            p.leftIndent = 15
            story.append(p)
            story.append(Spacer(1, 5))

    # 4. 결정 사항 (Decisions)
    decisions = meeting_data.get('decisions', [])
    if decisions:
        story.append(Paragraph("✅ Decisions", style_h1))
        items = []
        for d in decisions:
            items.append(ListItem(Paragraph(html.escape(d), style_normal), bulletColor=colors.black, value='circle'))
        story.append(ListFlowable(items, bulletType='bullet', start='circle', leftIndent=10))

    doc.build(story)
    buffer.seek(0)
    return buffer

# (기존 generate_review_pdf 함수 등은 반드시 포함되어 있어야 합니다)
# 아래는 예시로 review_pdf 함수도 함께 적어드립니다.
def generate_review_pdf(title, review_data, link=None):
    # ... (이전 답변의 코드 그대로 사용) ...
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    font_name = register_fonts()
    styles = getSampleStyleSheet()
    # ... (스타일 정의 생략) ...
    style_title = ParagraphStyle('DocTitle', parent=styles['Title'], fontName=font_name, fontSize=20, leading=24, spaceAfter=20, textColor=colors.darkblue)
    style_h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontName=font_name, fontSize=14, leading=18, spaceBefore=15, spaceAfter=10, textColor=colors.black)
    style_normal = ParagraphStyle('NormalText', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=16, spaceAfter=5)
    style_issue_desc = ParagraphStyle('IssueDesc', parent=styles['Normal'], fontName=font_name, fontSize=9, leading=12)

    story = []
    safe_title = html.escape(title)
    if link: safe_title += f' <link href="{link}" color="blue">[Link]</link>'
    story.append(Paragraph(f"<b>{safe_title}</b>", style_title))
    story.append(Spacer(1, 10))

    # Score & Summary
    if isinstance(review_data, dict):
        score = review_data.get('score', 0)
        score_color = "green" if score >= 80 else "orange" if score >= 50 else "red"
        story.append(Paragraph(f"<b>Code Quality Score:</b> <font color={score_color} size=12><b>{score}/100</b></font>", style_normal))
        summary = review_data.get('summary', '')
        story.append(Paragraph(f"<b>Summary:</b> {html.escape(summary)}", style_normal))
        story.append(Spacer(1, 15))
        
        # Issues
        issues = review_data.get('issues', [])
        if issues:
            story.append(Paragraph("🚨 Detected Issues", style_h1))
            data = [['Type', 'Severity', 'File', 'Description']]
            for issue in issues:
                desc_para = Paragraph(html.escape(issue.get('description', '')), style_issue_desc)
                data.append([issue.get('type', '-'), issue.get('severity', '-'), issue.get('file', '-') or 'General', desc_para])
            t = Table(data, colWidths=[60, 50, 100, 300])
            t.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), font_name), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
            story.append(t)
            story.append(Spacer(1, 15))
            
        # Suggestions
        suggestions = review_data.get('suggestions', [])
        if suggestions:
            story.append(Paragraph("💡 Suggestions", style_h1))
            list_items = [ListItem(Paragraph(html.escape(s), style_normal)) for s in suggestions]
            story.append(ListFlowable(list_items, bulletType='bullet', start='circle', leftIndent=10))
    else:
        story.append(Paragraph(html.escape(str(review_data)), style_normal))

    doc.build(story)
    buffer.seek(0)
    return buffer