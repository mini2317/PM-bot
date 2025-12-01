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
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT

def register_fonts():
    """한글 폰트 등록 및 사용 가능한 폰트 이름 반환"""
    font_path = "src/fonts/Nanum_Gothic/NanumGothic-Regular.ttf"
    font_name = 'Helvetica' # 기본값 (한글 미지원 시)
    
    try:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
            # 코드 블록용으로도 같은 폰트 사용 (한글 깨짐 방지 위해)
            font_name = 'NanumGothic'
        else:
            print(f"⚠️ 경고: 한글 폰트 파일을 찾을 수 없습니다. ({font_path})")
    except Exception as e:
        print(f"⚠️ 폰트 등록 실패: {e}")
    
    return font_name

def parse_markdown_to_flowables(text, styles, font_name):
    """
    마크다운 텍스트를 ReportLab Flowable 객체 리스트로 변환합니다.
    - 코드 블록 (```) -> 박스 스타일
    - 리스트 (-, *, 1.) -> 들여쓰기 적용
    - 헤더 (#) -> 큰 글씨
    - 인라인 스타일 (`, **) -> 스타일 적용
    """
    story = []
    
    # 1. 기본 스타일 정의
    style_normal = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=16, # 줄 간격
        spaceAfter=8
    )
    
    # 2. 코드 블록 스타일 정의 (회색 박스)
    style_code_block = ParagraphStyle(
        'CodeBlock',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.black,
        backColor=colors.whitesmoke, # 연한 회색 배경
        borderPadding=10,            # 내부 여백
        borderColor=colors.lightgrey,# 테두리 색
        borderWidth=0.5,             # 테두리 두께
        spaceAfter=15,
        wordWrap='CJK'               # 한글 줄바꿈 지원
    )

    # 3. 텍스트를 코드 블록(```) 기준으로 분리
    # 정규식 설명: ```(언어명 생략가능)\n(내용)
    parts = re.split(r'```(?:\w+)?\n(.*?)```', text, flags=re.DOTALL)
    for i, part in enumerate(parts):
        # 짝수 인덱스: 일반 텍스트, 홀수 인덱스: 코드 블록
        if i % 2 == 1:
            code_content = part.strip()
            if not code_content: continue
            
            # HTML 이스케이프 및 줄바꿈 처리
            # ReportLab Paragraph는 <br/>태그로 줄바꿈을 인식함
            escaped_code = html.escape(code_content).replace('\n', '<br/>')
            # 공백이 줄어들지 않도록 &nbsp;로 변환
            escaped_code = escaped_code.replace(' ', '&nbsp;')
            
            story.append(Paragraph(escaped_code, style_code_block))
        
        else:
            # 일반 텍스트 처리
            lines = part.split('\n')
            
            for line in lines:
                # 내용이 없는 완전 빈 줄은 스킵 (필요 시 Spacer 추가 가능)
                if not line.strip(): continue
                
                # 들여쓰기 레벨 계산 (공백 2칸당 1레벨)
                stripped_line = line.lstrip()
                indent_spaces = len(line) - len(stripped_line)
                indent_level = indent_spaces // 2
                
                # (1) 헤더 처리 (#, ##)
                if stripped_line.startswith('#'):
                    level = len(stripped_line.split(' ')[0]) # #의 개수
                    content = stripped_line.lstrip('#').strip()
                    
                    header_size = 18 - (level * 2) if level < 4 else 12
                    style_header = ParagraphStyle(
                        f'Header{level}',
                        parent=styles['Heading1'],
                        fontName=font_name,
                        fontSize=header_size,
                        leading=header_size + 4,
                        spaceBefore=10,
                        spaceAfter=6,
                        textColor=colors.darkblue
                    )
                    story.append(Paragraph(html.escape(content), style_header))
                    continue
                
                # (2) 리스트 처리 (-, *, 1.)
                is_list_item = False
                bullet = ""
                content = ""
                
                # Unordered List (-, *)
                if stripped_line.startswith('- ') or stripped_line.startswith('* '):
                    is_list_item = True
                    bullet = "•"
                    content = stripped_line[2:]
                
                # Ordered List (1., 2. 등)
                elif re.match(r'^\d+\.\s', stripped_line):
                    is_list_item = True
                    match = re.match(r'^(\d+\.)\s', stripped_line)
                    bullet = match.group(1)
                    content = stripped_line[match.end():]
                
                if is_list_item:
                    # 리스트용 스타일 생성 (들여쓰기 적용)
                    base_indent = 15
                    level_indent = 15 # 레벨당 추가 들여쓰기
                    
                    style_list = ParagraphStyle(
                        f'ListLevel{indent_level}',
                        parent=styles['Normal'],
                        fontName=font_name,
                        fontSize=10,
                        leading=16,
                        leftIndent=base_indent + (indent_level * level_indent),
                        firstLineIndent=-15, 
                        spaceAfter=3
                    )
                    
                    # 포맷팅 처리
                    processed_content = html.escape(content)
                    processed_content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', processed_content)
                    processed_content = re.sub(r'`([^`]+)`', r'<font backColor="#f0f0f0" name="Courier">&nbsp;\1&nbsp;</font>', processed_content)
                    
                    story.append(Paragraph(f"{bullet} {processed_content}", style_list))
                    continue

                # (3) 일반 텍스트 처리
                processed_line = html.escape(stripped_line)
                
                # 볼드 (**text**) -> <b>text</b>
                processed_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', processed_line)
                
                # 인라인 코드 (`text`) -> <font backColor>text</font>
                processed_line = re.sub(
                    r'`([^`]+)`', 
                    r'<font backColor="#f0f0f0" name="Courier">&nbsp;\1&nbsp;</font>', 
                    processed_line
                )
                
                story.append(Paragraph(processed_line, style_normal))

    return story

def generate_review_pdf(title, content):
    """
    제목과 마크다운 내용을 받아 PDF 바이너리를 반환합니다.
    """
    buffer = io.BytesIO()
    
    # 페이지 여백 설정
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=40, leftMargin=40, 
        topMargin=40, bottomMargin=40
    )
    
    font_name = register_fonts()
    styles = getSampleStyleSheet()
    
    # 문서 제목 스타일
    style_doc_title = ParagraphStyle(
        'DocTitle',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=24,
        leading=30,
        spaceAfter=30,
        alignment=TA_LEFT,
        textColor=colors.black
    )
    
    story = []
    
    # 1. 문서 제목 추가
    story.append(Paragraph(html.escape(title), style_doc_title))
    story.append(Spacer(1, 10))
    
    # 2. 본문 파싱 및 추가
    story.extend(parse_markdown_to_flowables(content, styles, font_name))
    
    # PDF 생성
    doc.build(story)
    buffer.seek(0)
    return buffer