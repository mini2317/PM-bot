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
from reportlab.lib.fonts import addMapping
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT

def register_fonts():
    """한글 폰트(Regular, Bold) 등록 - 경로 자동 탐색"""
    font_name = 'Helvetica' # 기본값 (한글 미지원 시)
    
    # 폰트가 있을만한 경로 후보들
    regular_candidates = [
        "src/fonts/NanumGothic-Regular.ttf",            # 바로 아래
        "src/fonts/Nanum_Gothic/NanumGothic-Regular.ttf" # 폴더 안
    ]
    
    bold_candidates = [
        "src/fonts/NanumGothic-Bold.ttf",
        "src/fonts/Nanum_Gothic/NanumGothic-Bold.ttf"
    ]

    regular_path = None
    for path in regular_candidates:
        if os.path.exists(path):
            regular_path = path
            break

    try:
        if regular_path:
            pdfmetrics.registerFont(TTFont('NanumGothic', regular_path))
            font_name = 'NanumGothic'
            
            # Bold 폰트 찾기 (Regular가 있는 경우에만 시도)
            bold_path = None
            for path in bold_candidates:
                if os.path.exists(path):
                    bold_path = path
                    break
            
            if bold_path:
                pdfmetrics.registerFont(TTFont('NanumGothic-Bold', bold_path))
                addMapping('NanumGothic', 0, 0, 'NanumGothic')
                addMapping('NanumGothic', 1, 0, 'NanumGothic-Bold')
        else:
            print(f"⚠️ 경고: 한글 폰트 파일을 찾을 수 없습니다. (src/fonts/ 폴더 확인 필요)")
            
    except Exception as e:
        print(f"⚠️ 폰트 등록 실패: {e}")
    
    return font_name

def parse_markdown_to_flowables(text, styles, font_name):
    """
    마크다운 텍스트를 ReportLab Flowable 객체 리스트로 변환합니다.
    """
    story = []
    
    style_normal = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=16,
        spaceAfter=8
    )
    
    # 코드 박스 스타일 (회색 배경 + 한글 폰트)
    style_code_block = ParagraphStyle(
        'CodeBlock',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.black,
        backColor=colors.whitesmoke,
        borderPadding=10,
        borderColor=colors.lightgrey,
        borderWidth=0.5,
        spaceAfter=15,
        wordWrap='CJK' # 한글 줄바꿈
    )

    # 정규식: 코드 블록(백틱 3개) 기준으로 텍스트 분리
    pattern = r'```(?:\w+)?\n(.*?)```'
    parts = re.split(pattern, text, flags=re.DOTALL)
    
    for i, part in enumerate(parts):
        if i % 2 == 1: # Code Block (홀수 인덱스는 코드 블록 내용)
            code_content = part.strip()
            if not code_content: continue
            
            # HTML 이스케이프 & 줄바꿈 처리
            escaped_code = html.escape(code_content).replace('\n', '<br/>')
            escaped_code = escaped_code.replace(' ', '&nbsp;')
            
            story.append(Paragraph(escaped_code, style_code_block))
        else:
            # Normal Text (짝수 인덱스는 일반 텍스트)
            lines = part.split('\n')
            for line in lines:
                if not line.strip(): continue
                
                stripped_line = line.lstrip()
                indent_level = (len(line) - len(stripped_line)) // 2
                
                # Header (#)
                if stripped_line.startswith('#'):
                    level = len(stripped_line.split(' ')[0])
                    content = stripped_line.lstrip('#').strip()
                    h_size = 18 - (level*2) if level < 4 else 12
                    
                    style_h = ParagraphStyle(
                        f'Header{level}', parent=styles['Heading1'],
                        fontName=font_name, fontSize=h_size, leading=h_size+4,
                        spaceBefore=10, spaceAfter=6, textColor=colors.darkblue
                    )
                    # 헤더는 굵게
                    story.append(Paragraph(f"<b>{html.escape(content)}</b>", style_h))
                    continue
                
                # List (-, *, 1.)
                bullet = ""
                content = ""
                is_list = False
                
                if stripped_line.startswith(('- ', '* ')):
                    is_list = True; bullet = "•"; content = stripped_line[2:]
                elif re.match(r'^\d+\.\s', stripped_line):
                    is_list = True
                    m = re.match(r'^(\d+\.)\s', stripped_line)
                    bullet = m.group(1); content = stripped_line[m.end():]
                
                # 인라인 스타일 처리 함수
                def process_inline(txt):
                    txt = html.escape(txt)
                    txt = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', txt) # Bold
                    # 인라인 코드: 배경색 + 같은 폰트(깨짐 방지)
                    txt = re.sub(r'`([^`]+)`', f'<font backColor="#f0f0f0" name="{font_name}">&nbsp;\\1&nbsp;</font>', txt)
                    return txt

                final_text = process_inline(content if is_list else stripped_line)
                
                if is_list:
                    style_list = ParagraphStyle(
                        f'ListLvl{indent_level}', parent=styles['Normal'],
                        fontName=font_name, fontSize=10, leading=16,
                        leftIndent=15 + (indent_level*15), firstLineIndent=-15, spaceAfter=3
                    )
                    story.append(Paragraph(f"{bullet} {final_text}", style_list))
                else:
                    story.append(Paragraph(final_text, style_normal))

    return story

def generate_review_pdf(title, review_data, link=None):
    """
    review_data(JSON Dict 또는 Str)를 받아 구조화된 PDF를 생성합니다.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    font_name = register_fonts()
    styles = getSampleStyleSheet()
    
    # 스타일 정의
    style_title = ParagraphStyle('DocTitle', parent=styles['Title'], fontName=font_name, fontSize=20, leading=24, spaceAfter=20, textColor=colors.darkblue)
    style_h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontName=font_name, fontSize=14, leading=18, spaceBefore=15, spaceAfter=10, textColor=colors.black)
    style_normal = ParagraphStyle('NormalText', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=16, spaceAfter=5)
    style_issue_desc = ParagraphStyle('IssueDesc', parent=styles['Normal'], fontName=font_name, fontSize=9, leading=12)

    story = []
    
    # 제목 처리
    safe_title = html.escape(title)
    if link:
        safe_title += f' <link href="{link}" color="blue">[Link]</link>'
    story.append(Paragraph(f"<b>{safe_title}</b>", style_title))
    story.append(Spacer(1, 10))

    if isinstance(review_data, dict):
        # 점수 및 요약
        score = review_data.get('score', 0)
        score_color = "green" if score >= 80 else "orange" if score >= 50 else "red"
        story.append(Paragraph(f"<b>Code Quality Score:</b> <font color={score_color} size=12><b>{score}/100</b></font>", style_normal))
        
        summary = review_data.get('summary', '')
        story.append(Paragraph(f"<b>Summary:</b> {html.escape(summary)}", style_normal))
        story.append(Spacer(1, 15))
        
        # 이슈 테이블
        issues = review_data.get('issues', [])
        if issues:
            story.append(Paragraph("🚨 Detected Issues", style_h1))
            data = [['Type', 'Severity', 'File', 'Description']]
            for issue in issues:
                # 문자열로 들어올 경우 방어 처리
                if isinstance(issue, dict):
                    i_type = issue.get('type', '-')
                    i_severity = issue.get('severity', '-')
                    i_file = issue.get('file', '-') or 'General'
                    i_desc = issue.get('description', '')
                else:
                    i_type, i_severity, i_file = '-', '-', '-'
                    i_desc = str(issue)

                desc_para = Paragraph(html.escape(i_desc), style_issue_desc)
                data.append([i_type, i_severity, i_file, desc_para])
            
            t = Table(data, colWidths=[60, 50, 100, 300])
            t.setStyle(TableStyle([
                ('FONTNAME', (0,0), (-1,-1), font_name),
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                ('VALIGN', (0,0), (-1,-1), 'TOP')
            ]))
            story.append(t)
            story.append(Spacer(1, 15))
            
        # 제안 사항
        suggestions = review_data.get('suggestions', [])
        if suggestions:
            story.append(Paragraph("💡 Suggestions", style_h1))
            list_items = [ListItem(Paragraph(html.escape(str(s)), style_normal), bulletColor=colors.black, value='circle') for s in suggestions]
            story.append(ListFlowable(list_items, bulletType='bullet', start='circle', leftIndent=10))
    else:
        # 딕셔너리가 아닌 경우 일반 텍스트로 처리
        story.extend(parse_markdown_to_flowables(str(review_data), styles, font_name))

    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_meeting_pdf(meeting_data):
    """
    회의록 JSON 데이터를 PDF로 변환합니다.
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
            if isinstance(item, dict):
                topic = item.get('topic', 'Topic')
                content = item.get('content', '')
            else:
                topic = "Agenda Item"
                content = str(item)
                
            story.append(Paragraph(f"<b>• {html.escape(topic)}</b>", style_normal))
            p = Paragraph(html.escape(content), style_normal)
            p.leftIndent = 15
            story.append(p)
            story.append(Spacer(1, 5))

    # 4. 결정 사항 (Decisions)
    decisions = meeting_data.get('decisions', [])
    if decisions:
        story.append(Paragraph("✅ Decisions", style_h1))
        items = [ListItem(Paragraph(html.escape(str(d)), style_normal), bulletColor=colors.black, value='circle') for d in decisions]
        story.append(ListFlowable(items, bulletType='bullet', start='circle', leftIndent=10))

    doc.build(story)
    buffer.seek(0)
    return buffer