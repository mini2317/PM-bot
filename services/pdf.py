import io
import os
import re
import html
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.lib.enums import TA_LEFT

def register_fonts():
    """한글 폰트(Regular, Bold) 등록"""
    font_dir = "src/fonts/Nanum_Gothic"
    regular_path = os.path.join(font_dir, "NanumGothic-Regular.ttf")
    bold_path = os.path.join(font_dir, "NanumGothic-Bold.ttf")
    font_name = 'Helvetica' # 기본값 (한글 미지원)
    
    try:
        if os.path.exists(regular_path):
            pdfmetrics.registerFont(TTFont('NanumGothic', regular_path))
            font_name = 'NanumGothic'
            
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont('NanumGothic-Bold', bold_path))
                # <b> 태그 사용 시 자동으로 Bold 폰트 매핑
                addMapping('NanumGothic', 0, 0, 'NanumGothic')
                addMapping('NanumGothic', 1, 0, 'NanumGothic-Bold')
        else:
            print(f"⚠️ 경고: 폰트 파일 없음 ({regular_path})")
    except Exception as e:
        print(f"⚠️ 폰트 등록 실패: {e}")
    
    return font_name

def parse_markdown_to_flowables(text, styles, font_name):
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

    # 정규식: 코드 블록(```) 기준으로 텍스트 분리
    parts = re.split(r'```(?:\w+)?\n(.*?)```', text, flags=re.DOTALL)
    for i, part in enumerate(parts):
        if i % 2 == 1: # Code Block
            code_content = part.strip()
            if not code_content: continue
            
            # HTML 이스케이프 & 줄바꿈 처리
            escaped_code = html.escape(code_content).replace('\n', '<br/>')
            escaped_code = escaped_code.replace(' ', '&nbsp;')
            
            story.append(Paragraph(escaped_code, style_code_block))
        else:
            # Normal Text
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

def generate_review_pdf(title, content, link=None):
    """
    PDF 생성. link가 있으면 제목의 (...) 부분에 하이퍼링크를 겁니다.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    font_name = register_fonts()
    styles = getSampleStyleSheet()
    
    # 문서 제목 스타일 (Bold)
    style_title = ParagraphStyle(
        'DocTitle', parent=styles['Title'],
        fontName=font_name, fontSize=24, leading=30,
        spaceAfter=30, alignment=TA_LEFT, textColor=colors.black
    )
    
    story = []
    
    # 제목 처리: 링크 적용 (괄호 안의 ID 부분)
    safe_title = html.escape(title)
    if link:
        # 마지막 괄호 (...) 부분을 찾아 링크 태그로 감쌈
        safe_title = re.sub(r'\(([^)]+)\)$', f'(<link href="{link}" color="blue">\\1</link>)', safe_title)

    # 제목은 항상 굵게
    story.append(Paragraph(f"<b>{safe_title}</b>", style_title))
    story.append(Spacer(1, 10))
    
    # 본문 추가
    story.extend(parse_markdown_to_flowables(content, styles, font_name))
    
    doc.build(story)
    buffer.seek(0)
    return buffer