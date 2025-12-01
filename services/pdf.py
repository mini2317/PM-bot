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
        else:
            print(f"⚠️ 경고: 한글 폰트 파일을 찾을 수 없습니다. ({font_path})")
    except Exception as e:
        print(f"⚠️ 폰트 등록 실패: {e}")
    
    return font_name

def generate_review_pdf(title, review_data, link=None):
    """
    review_data(JSON Dict)를 받아 구조화된 PDF를 생성합니다.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    font_name = register_fonts()
    styles = getSampleStyleSheet()
    
    # --- Styles ---
    style_title = ParagraphStyle('DocTitle', parent=styles['Title'], fontName=font_name, fontSize=20, leading=24, spaceAfter=20, textColor=colors.darkblue)
    style_h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontName=font_name, fontSize=14, leading=18, spaceBefore=15, spaceAfter=10, textColor=colors.black)
    style_normal = ParagraphStyle('NormalText', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=16, spaceAfter=5)
    style_issue_desc = ParagraphStyle('IssueDesc', parent=styles['Normal'], fontName=font_name, fontSize=9, leading=12)
    
    story = []
    
    # 1. Title
    safe_title = html.escape(title)
    if link:
        safe_title += f' <link href="{link}" color="blue">[Link]</link>'
    story.append(Paragraph(f"<b>{safe_title}</b>", style_title))
    story.append(Spacer(1, 10))
    
    # 2. Score & Summary
    score = review_data.get('score', 0)
    score_color = "green" if score >= 80 else "orange" if score >= 50 else "red"
    story.append(Paragraph(f"<b>Code Quality Score:</b> <font color={score_color} size=12><b>{score}/100</b></font>", style_normal))
    
    summary = review_data.get('summary', '요약 없음')
    story.append(Paragraph(f"<b>Summary:</b> {html.escape(summary)}", style_normal))
    story.append(Spacer(1, 15))

    # 3. Issues Table
    issues = review_data.get('issues', [])
    if issues:
        story.append(Paragraph("🚨 Detected Issues", style_h1))
        
        # Table Header
        data = [['Type', 'Severity', 'File', 'Description']]
        
        for issue in issues:
            # 긴 텍스트는 Paragraph로 감싸서 자동 줄바꿈 되도록 처리
            desc_para = Paragraph(html.escape(issue.get('description', '')), style_issue_desc)
            data.append([
                issue.get('type', '-'),
                issue.get('severity', '-'),
                issue.get('file', '-') or 'General',
                desc_para
            ])
            
        # 테이블 스타일
        t = Table(data, colWidths=[60, 50, 100, 300])
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), # Header BG
            ('TEXTCOLOR', (0,0), (-1,0), colors.black),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('fontName', (0,0), (-1,-1), font_name),
            ('fontSize', (0,0), (-1,-1), 9),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 15))
        
    # 4. Suggestions List
    suggestions = review_data.get('suggestions', [])
    if suggestions:
        story.append(Paragraph("💡 Suggestions", style_h1))
        
        list_items = []
        for sug in suggestions:
            list_items.append(ListItem(Paragraph(html.escape(sug), style_normal), bulletColor=colors.black, value='circle'))
            
        story.append(ListFlowable(list_items, bulletType='bullet', start='circle', leftIndent=10))

    doc.build(story)
    buffer.seek(0)
    return buffer