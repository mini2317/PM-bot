import io
import os
import re
import html
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER

# --- Configuration ---
THEME_COLOR = colors.HexColor('#2C3E50') # Dark Blue/Grey
ACCENT_COLOR = colors.HexColor('#E74C3C') # Red for alerts
HEADER_BG = colors.HexColor('#ECF0F1') # Light Grey for table headers
CODE_BG = colors.HexColor('#F8F9F9')   # Very light grey for code
BORDER_COLOR = colors.HexColor('#BDC3C7')

def register_fonts():
    """한글 폰트(Regular, Bold) 등록 - 경로 자동 탐색"""
    font_name = 'Helvetica' # 기본값
    
    regular_candidates = [
        "src/fonts/NanumGothic-Regular.ttf",            
        "src/fonts/Nanum_Gothic/NanumGothic-Regular.ttf" 
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
            
            bold_path = None
            for path in bold_candidates:
                if os.path.exists(path):
                    bold_path = path
                    break
            
            if bold_path:
                pdfmetrics.registerFont(TTFont('NanumGothic-Bold', bold_path))
                addMapping('NanumGothic', 0, 0, 'NanumGothic')
                addMapping('NanumGothic', 1, 0, 'NanumGothic-Bold')
                addMapping('NanumGothic', 0, 1, 'NanumGothic-Bold') # Italic hack
                addMapping('NanumGothic', 1, 1, 'NanumGothic-Bold')
        else:
            print(f"⚠️ 경고: 한글 폰트 파일을 찾을 수 없습니다. (src/fonts/ 폴더 확인 필요)")
    except Exception as e:
        print(f"⚠️ 폰트 등록 실패: {e}")
    
    return font_name

def get_stylesheet(font_name):
    styles = getSampleStyleSheet()
    
    # Title
    styles.add(ParagraphStyle(
        name='ReportTitle',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=24,
        leading=30,
        textColor=THEME_COLOR,
        spaceAfter=20,
        alignment=TA_LEFT
    ))

    # Heading 1
    styles.add(ParagraphStyle(
        name='ReportH1',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=16,
        leading=20,
        textColor=THEME_COLOR,
        spaceBefore=15,
        spaceAfter=10,
        borderPadding=5,
        borderWidth=0,
        borderBottomWidth=1,
        borderColor=BORDER_COLOR
    ))

    # Normal Text
    styles.add(ParagraphStyle(
        name='ReportNormal',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=16,
        spaceAfter=8,
        alignment=TA_JUSTIFY
    ))

    # Code Block
    styles.add(ParagraphStyle(
        name='ReportCode',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.black,
        backColor=CODE_BG,
        borderPadding=10,
        borderColor=BORDER_COLOR,
        borderWidth=0.5,
        spaceAfter=15,
        leftIndent=5,
        rightIndent=5,
        wordWrap='CJK'
    ))

    # Table Cell
    styles.add(ParagraphStyle(
        name='TableCell',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=12,
        alignment=TA_LEFT
    ))

    return styles

def parse_markdown_to_flowables(text, styles, font_name):
    story = []
    
    # Regex for code blocks
    pattern = r'```(?:\w+)?\n(.*?)```'
    parts = re.split(pattern, text, flags=re.DOTALL)
    
    for i, part in enumerate(parts):
        if i % 2 == 1: # Code Block
            code_content = part.strip()
            if not code_content: continue
            escaped_code = html.escape(code_content).replace('\n', '<br/>').replace(' ', '&nbsp;')
            story.append(Paragraph(escaped_code, styles['ReportCode']))
        else:
            # Normal Text
            lines = part.split('\n')
            for line in lines:
                if not line.strip(): continue
                stripped_line = line.lstrip()
                
                # Headers
                if stripped_line.startswith('#'):
                    level = len(stripped_line.split(' ')[0])
                    content = stripped_line.lstrip('#').strip()
                    # Use H1 style for all headers for simplicity, or adjust
                    story.append(Paragraph(f"<b>{html.escape(content)}</b>", styles['ReportH1']))
                    continue
                
                # Lists
                bullet = ""
                content = ""
                is_list = False
                
                if stripped_line.startswith(('- ', '* ')):
                    is_list = True; bullet = "•"; content = stripped_line[2:]
                elif re.match(r'^\d+\.\s', stripped_line):
                    is_list = True
                    m = re.match(r'^(\d+\.)\s', stripped_line)
                    bullet = m.group(1); content = stripped_line[m.end():]

                # Inline Styles
                def process_inline(txt):
                    txt = html.escape(txt)
                    txt = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', txt)
                    txt = re.sub(r'`([^`]+)`', f'<font backColor="{CODE_BG.hexval()}" name="{font_name}">&nbsp;\\1&nbsp;</font>', txt)
                    return txt

                final_text = process_inline(content if is_list else stripped_line)
                
                if is_list:
                    # Custom List Style
                    list_style = ParagraphStyle(
                        'ListItem',
                        parent=styles['ReportNormal'],
                        leftIndent=20,
                        firstLineIndent=-15
                    )
                    story.append(Paragraph(f"{bullet} {final_text}", list_style))
                else:
                    story.append(Paragraph(final_text, styles['ReportNormal']))

    return story

def generate_review_pdf(title, review_data, link=None):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm, 
        topMargin=20*mm, bottomMargin=20*mm
    )
    
    font_name = register_fonts()
    styles = get_stylesheet(font_name)
    
    story = []
    
    # Title
    safe_title = html.escape(title)
    if link:
        safe_title += f' <link href="{link}" color="#3498DB">[Link]</link>'
    story.append(Paragraph(safe_title, styles['ReportTitle']))
    story.append(HRFlowable(width="100%", thickness=2, color=THEME_COLOR))
    story.append(Spacer(1, 15))

    if isinstance(review_data, dict):
        # Score
        score = review_data.get('score', 0)
        score_color = "#27AE60" if score >= 80 else "#F39C12" if score >= 50 else "#C0392B"
        story.append(Paragraph(f"<b>Code Quality Score:</b> <font color={score_color} size=14><b>{score}/100</b></font>", styles['ReportNormal']))
        
        # Summary
        summary = review_data.get('summary', '')
        story.append(Paragraph(f"<b>Summary:</b>", styles['ReportH1']))
        story.append(Paragraph(html.escape(summary), styles['ReportNormal']))
        
        # Issues Table
        issues = review_data.get('issues', [])
        if issues:
            story.append(Paragraph("🚨 Detected Issues", styles['ReportH1']))
            
            table_data = [[
                Paragraph('<b>Type</b>', styles['TableCell']),
                Paragraph('<b>Severity</b>', styles['TableCell']),
                Paragraph('<b>File</b>', styles['TableCell']),
                Paragraph('<b>Description</b>', styles['TableCell'])
            ]]
            
            for issue in issues:
                if isinstance(issue, dict):
                    i_type = issue.get('type', '-')
                    i_sev = issue.get('severity', '-')
                    i_file = issue.get('file', '-') or 'General'
                    i_desc = issue.get('description', '')
                else:
                    i_type, i_sev, i_file = '-', '-', '-'
                    i_desc = str(issue)

                # Severity Color
                sev_color = colors.black
                if i_sev == '상': sev_color = colors.red
                elif i_sev == '중': sev_color = colors.orange
                
                table_data.append([
                    Paragraph(i_type, styles['TableCell']),
                    Paragraph(f'<font color="{sev_color}">{i_sev}</font>', styles['TableCell']),
                    Paragraph(i_file, styles['TableCell']),
                    Paragraph(html.escape(i_desc), styles['TableCell'])
                ])
            
            # Column Widths (Total ~170mm)
            col_widths = [25*mm, 20*mm, 40*mm, 85*mm]
            t = Table(table_data, colWidths=col_widths, repeatRows=1)
            
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
                ('TEXTCOLOR', (0,0), (-1,0), THEME_COLOR),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.whitesmoke]),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('TOPPADDING', (0,0), (-1,-1), 6),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ]))
            story.append(t)
            
        # Suggestions
        suggestions = review_data.get('suggestions', [])
        if suggestions:
            story.append(Paragraph("💡 Suggestions", styles['ReportH1']))
            for s in suggestions:
                story.append(Paragraph(f"• {html.escape(str(s))}", styles['ReportNormal']))
                
    else:
        # Fallback for text content
        story.extend(parse_markdown_to_flowables(str(review_data), styles, font_name))

    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_meeting_pdf(meeting_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm, 
        topMargin=20*mm, bottomMargin=20*mm
    )
    
    font_name = register_fonts()
    styles = get_stylesheet(font_name)
    
    story = []
    
    # Header
    title = meeting_data.get('title', '회의록')
    date = meeting_data.get('date', '-')
    story.append(Paragraph(html.escape(title), styles['ReportTitle']))
    story.append(Paragraph(f"<b>Date:</b> {date}", styles['ReportNormal']))
    story.append(HRFlowable(width="100%", thickness=2, color=THEME_COLOR))
    story.append(Spacer(1, 15))

    # Summary
    summary = meeting_data.get('summary', '')
    if summary:
        story.append(Paragraph("📌 Summary", styles['ReportH1']))
        # Box effect
        story.append(Paragraph(html.escape(summary), styles['ReportCode'])) # Reusing Code style for box effect

    # Agenda
    agenda = meeting_data.get('agenda', [])
    if agenda:
        story.append(Paragraph("📋 Agenda & Discussions", styles['ReportH1']))
        
        table_data = [[Paragraph('<b>Topic</b>', styles['TableCell']), Paragraph('<b>Content</b>', styles['TableCell'])]]
        
        for item in agenda:
            if isinstance(item, dict):
                topic = item.get('topic', 'Topic')
                content = item.get('content', '')
            else:
                topic = "Agenda"
                content = str(item)
            
            table_data.append([
                Paragraph(f"<b>{html.escape(topic)}</b>", styles['TableCell']),
                Paragraph(html.escape(content), styles['TableCell'])
            ])
            
        col_widths = [40*mm, 130*mm]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
            ('TEXTCOLOR', (0,0), (-1,0), THEME_COLOR),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.whitesmoke]),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(t)

    # Decisions
    decisions = meeting_data.get('decisions', [])
    if decisions:
        story.append(Paragraph("✅ Key Decisions", styles['ReportH1']))
        for d in decisions:
            # Checkbox style bullet
            story.append(Paragraph(f"☑  {html.escape(str(d))}", styles['ReportNormal']))

    doc.build(story)
    buffer.seek(0)
    return buffer