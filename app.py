import base64
import json
import os
from io import BytesIO
from pathlib import Path

import streamlit as st
import pdfplumber
import pytesseract
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pdf2image import convert_from_bytes
from PIL import Image
from zhipuai import ZhipuAI

from format_parser import get_default_config, parse_markdown
from doc_generator import generate_docx, doc_to_bytes

# 加载 .env 文件中的环境变量
load_dotenv()


# ======================
# 多语言文本配置与助手
# ======================

TEXTS = {
    "en": {
        "app_title": "Doc. - AI Format Assistant",
        "subtitle": "Upload format requirements and Markdown, then generate a submission‑ready Word document.",
        "sidebar_title": "Help",
        "sidebar_step1": "Format: upload syllabus (PDF / image / HTML / Markdown) or paste text.",
        "sidebar_step2": "Content: paste Markdown from AI tools (# / ## headings are most stable).",
        "sidebar_step3": "Generate: click the bottom buttons to create & download Word.",
        "tutorial_title": "Quick start",
        "tutorial_step1_title": "1  Import format requirements",
        "tutorial_step1_desc": "Upload syllabus (PDF / image / HTML / MD) or paste only the format section.",
        "tutorial_step2_title": "2  Paste Markdown content",
        "tutorial_step2_desc": "Copy from AI tools and mark headings with # / ## for better recognition.",
        "tutorial_step3_title": "3  Generate & download",
        "tutorial_step3_desc": "Click the bottom button to generate, then download the .docx file.",
        "tutorial_button": "Start",
        "section_format": "Format requirements",
        "section_content": "Content (Markdown)",
        "uploader_format_label": "Format file",
        "uploader_format_help": "Upload syllabus or format description: PDF, image, HTML, Markdown.",
        "format_text_placeholder": "e.g. Times New Roman 12pt, double spacing, 1‑inch margins, APA 7th edition, title centered and bold, page numbers top‑right…",
        "content_text_placeholder": "Paste your content: # for title, ## for heading1, plain paragraphs for body…",
        "warn_need_content": "Please paste or type the Markdown content on the right first.",
        "success_generated": "Document generated. Click the arrow on the right to download.",
        "error_generating": "Error occurred while generating document: ",
        "image_preview_caption": "Format file preview",
        "spinner_recognizing_image": "Recognizing format requirements from image...",
        "success_format_recognized": "Format requirements recognized. Please confirm or edit.",
        "warn_image_not_recognized": "Could not reliably recognize format from image. Try uploading PDF or paste manually.",
        "spinner_auto_detecting": "Auto-detecting format requirements...",
        "success_format_auto_detected": "Format requirements auto-detected. Please confirm or edit.",
        "info_format_not_detected": "Could not auto-detect format requirements. Full content loaded for manual selection.",
        "warn_file_empty": "File is empty or cannot be read.",
        "spinner_generating": "Generating document, please wait...",
        "content_uploader_label": "Content file (Markdown only)",
        "content_uploader_help": "Upload .md / markdown files exported from AI tools.",
    },
    "zh": {
        "app_title": "Doc. - AI 格式助手",
        "subtitle": "上传格式要求和 Markdown，一键生成可提交的 Word 文档。",
        "sidebar_title": "帮助",
        "sidebar_step1": "格式要求：上传 syllabus（PDF/图片/HTML/Markdown）或直接粘贴。",
        "sidebar_step2": "内容：推荐从 AI 应用复制粘贴 Markdown（# / ## 标题最稳定）。",
        "sidebar_step3": "生成：点击底部按钮生成并下载 Word。",
        "tutorial_title": "快速上手",
        "tutorial_step1_title": "1  导入格式要求",
        "tutorial_step1_desc": "上传 syllabus（PDF/图片/HTML/MD）或直接粘贴格式要求片段。",
        "tutorial_step2_title": "2  粘贴 Markdown 内容",
        "tutorial_step2_desc": "从 AI 应用复制内容，标题用 # / ## 标注更稳定。",
        "tutorial_step3_title": "3  生成并下载",
        "tutorial_step3_desc": "点击底部按钮生成文档，再下载 .docx 提交。",
        "tutorial_button": "开始使用",
        "section_format": "格式要求",
        "section_content": "内容（Markdown）",
        "uploader_format_label": "格式文件",
        "uploader_format_help": "上传 syllabus 或格式说明：PDF、图片、HTML、Markdown。",
        "format_text_placeholder": "例如：A4 纸张、2.5cm 页边距、宋体小四、1.5 倍行距、标题加粗居中、脚注格式等…",
        "content_text_placeholder": "粘贴你的内容：# 表示主标题，## 表示一级标题，正文使用普通段落…",
        "warn_need_content": "请先在右侧输入或粘贴要转换的 Markdown 内容。",
        "success_generated": "已生成文档，可点击右侧图标下载。",
        "error_generating": "生成文档时出现错误：",
        "image_preview_caption": "格式文件预览",
        "spinner_recognizing_image": "正在从图片中识别格式要求...",
        "success_format_recognized": "已识别格式要求，请确认并可手动修改。",
        "warn_image_not_recognized": "未能可靠识别图片中的格式要求，请尝试上传 PDF 或手动粘贴。",
        "spinner_auto_detecting": "正在自动识别格式要求...",
        "success_format_auto_detected": "已自动识别格式要求，请确认并可手动修改。",
        "info_format_not_detected": "未能自动识别格式要求，已填充全部内容供你手动筛选。",
        "warn_file_empty": "文件内容为空或无法读取。",
        "spinner_generating": "正在生成文档，请稍候...",
        "content_uploader_label": "内容文件（仅 Markdown）",
        "content_uploader_help": "可以上传从 AI 应用导出的 .md / markdown 文件。",
    },
}


def t(key: str) -> str:
    """根据当前语言返回文案，默认英文。"""
    lang = st.session_state.get("lang", "en")
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)


# ======================
# LLM 调用公共辅助函数
# ======================

def _get_zhipu_client():
    """获取ZhipuAI客户端，如果API key不存在则返回None。"""
    api_key = os.getenv("ZHIPU_API_KEY")
    if not api_key:
        return None
    return ZhipuAI(api_key=api_key)


def _call_zhipu_llm(
    prompt: str,
    model: str = "glm-4-flash",
    temperature: float = 0.1,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
) -> str:
    """通用ZhipuAI LLM调用函数。
    
    Args:
        prompt: 文本提示
        model: 模型名称，默认为 "glm-4-flash"
        temperature: 温度参数，默认为 0.1
        image_url: 可选的单张图片URL（用于多模态调用）
        image_urls: 可选的多张图片URL列表（用于一次性处理整个PDF）
    
    Returns:
        模型返回的文本内容，如果调用失败则返回空字符串
    """
    client = _get_zhipu_client()
    if not client:
        return ""
    
    try:
        if image_urls:
            # 多图片调用：一次性发送整个PDF的所有页面给AI
            content_items = [{"type": "text", "text": prompt}]
            for img_url in image_urls:
                content_items.append({
                    "type": "image_url",
                    "image_url": {"url": img_url}
                })
            messages = [{"role": "user", "content": content_items}]
        elif image_url:
            # 单图片调用（保持兼容）
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ]
        else:
            # 纯文本调用
            messages = [{"role": "user", "content": prompt}]
        
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        content = (resp.choices[0].message.content or "").strip()
        return content
    except Exception:
        return ""


def _extract_json_from_text(content: str, bracket_type: str = "{") -> dict | list | None:
    """从文本中提取JSON对象或数组。
    
    Args:
        content: 包含JSON的文本
        bracket_type: 括号类型，"{" 表示对象，"[" 表示数组
    
    Returns:
        解析后的JSON对象或数组，如果提取失败则返回None
    """
    try:
        if bracket_type == "{":
            start = content.find("{")
            end = content.rfind("}")
        else:  # "["
            start = content.find("[")
            end = content.rfind("]")
        
        if start != -1 and end != -1 and end > start:
            json_str = content[start : end + 1]
            return json.loads(json_str)
    except Exception:
        pass
    return None

def parse_uploaded_file(uploaded_file, max_pdf_pages: int | None = None) -> tuple[str, str]:
    """根据文件类型尝试提取格式要求与正文内容（最小实现版）。

    - md/markdown：读取为文本
    - html/htm：提取页面可见文本
    - pdf：提取/识别为纯文本（多模态 OCR -> 文本提取 -> 本地 OCR 回退）
    返回 (format_requirements, markdown_content)，当前统一返回为正文文本，由调用方决定用途。
    
    Args:
        uploaded_file: 上传的文件对象
        max_pdf_pages: 对于PDF文件，限制OCR的最大页数。用于格式要求识别时可设为3以提高速度。
    """
    suffix = Path(uploaded_file.name).suffix.lower()
    data = uploaded_file.read()

    def decode_text(raw: bytes) -> str:
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return ""

    if suffix in {".md", ".markdown"}:
        # 直接视为 Markdown 文本，不区分格式/正文，由调用方决定用在哪一侧
        return "", decode_text(data)

    if suffix in {".html", ".htm"}:
        html = decode_text(data)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n")
        return "", text

    if suffix == ".pdf":
        # PDF 通用解析：先转文本，再视具体场景使用
        # 对于格式要求识别，可以只OCR前几页以提高速度
        text = extract_pdf_text(data, max_pages=max_pdf_pages)
        # 默认作为正文返回；格式侧会额外调用 LLM 只提取格式要求
        return "", text

    return "", ""


def extract_pdf_text(raw: bytes, max_pages: int | None = None) -> str:
    """优先用智谱多模态做 OCR；失败时退回本地 pdfplumber + Tesseract。
    
    Args:
        raw: PDF 文件的字节数据
        max_pages: 最大OCR页数，用于格式要求识别时可限制为前3页以提高速度。
    """
    # 1) 优先：智谱多模态逐页 OCR
    text = zhipu_ocr_from_pdf(raw, max_pages=max_pages)
    if text and len(text.strip()) > 20:
        return text.strip()

    # 2) 回退：pdfplumber 文本提取
    try:
        with pdfplumber.open(BytesIO(raw)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
    except Exception:
        text = ""

    # 3) 再回退：本地 Tesseract OCR
    if not text or len(text) < 20:
        try:
            images = convert_from_bytes(raw, dpi=300)
            ocr_texts = []
            for img in images:
                if not isinstance(img, Image.Image):
                    img = Image.fromarray(img)
                ocr_texts.append(pytesseract.image_to_string(img, lang="chi_sim+eng"))
            text = "\n".join(ocr_texts).strip()
        except Exception:
            pass

    return text or ""


def zhipu_ocr_from_pdf(raw: bytes, max_pages: int | None = None) -> str:
    """使用智谱多模态模型对 PDF 各页图片进行 OCR。
    
    Args:
        raw: PDF 文件的字节数据
        max_pages: 最大OCR页数，如果为None则OCR所有页面。用于格式要求识别时可限制为前几页以提高速度。
    """
    client = _get_zhipu_client()
    if not client:
        return ""

    try:
        images = convert_from_bytes(raw, dpi=256)
        # 如果指定了最大页数，只处理前几页
        if max_pages is not None and max_pages > 0:
            images = images[:max_pages]
        
        page_texts: list[str] = []

        prompt = (
            "请对这张页面图片做精准 OCR，将页面内容完整准确地转写为文本：\n"
            "- 逐字转写页面中的所有中文和英文内容；\n"
            "- 保留文档的结构和层次，特别是标题、段落、列表等格式；\n"
            "- 识别并保留标题标记（如\"一、\"、\"二、\"、\"（一）\"、\"（二）\"等编号）；\n"
            "- 识别并保留章节标题、小节标题等层级结构；\n"
            "- 只做必要的断行和空格修正，不要改写句子、不要总结、不要补充内容；\n"
            "- 保持原文的段落分隔和格式；\n"
            "- 不要添加任何解释、总结或前后缀。"
        )

        for img in images:
            buf = BytesIO()
            img.save(buf, format="JPEG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{b64}"

            content = _call_zhipu_llm(
                prompt=prompt,
                model="glm-4v",
                temperature=0.1,
                image_url=data_url,
            )
            if content:
                page_texts.append(content)

        return "\n\n".join(page_texts).strip()
    except Exception:
        return ""


def extract_format_from_image(raw: bytes) -> str:
    """使用智谱多模态模型从格式要求截图中提取文字（侧重排版/格式描述）。"""
    try:
        img = Image.open(BytesIO(raw))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

        prompt = (
            "这是一张课程 syllabus 或作业说明的截图。请**先快速识别**图片中哪部分内容是【排版/格式要求】，然后**只转写那部分内容**。\n\n"
            "**识别策略**：\n"
            "- 格式要求通常出现在文档的开头部分、独立章节（如\"格式要求\"、\"提交格式\"、\"排版规范\"等标题下）\n"
            "- 格式要求通常包含具体的数值和单位（如\"12pt\"、\"2.5cm\"、\"1.5倍行距\"）\n"
            "- 格式要求通常描述排版样式，而不是内容主题\n\n"
            "**需要提取的格式要求包括**：\n"
            "- 纸张大小（如 A4、Letter）\n"
            "- 页边距（如上2.5cm、下2.5cm、左3cm、右1.5cm）\n"
            "- 字体和字号（如宋体小四、Times New Roman 12pt、黑体三号）\n"
            "- 行距（如单倍行距、1.5倍行距、固定值22磅）\n"
            "- 标题级别与样式（如一级标题加粗居中、二级标题左对齐）\n"
            "- 段落格式（如首行缩进2字符、段前段后间距）\n"
            "- 引用/脚注/参考文献格式要求\n"
            "- 页眉页脚、页码格式等\n\n"
            "**严格排除以下非格式内容**：\n"
            "- 课程名称、课程介绍、课程目标\n"
            "- 作业题目、写作主题、内容要求\n"
            "- 字数要求、提交时间、截止日期\n"
            "- 评分标准、评分细则、课程安排\n"
            "- 参考文献列表、课程资料等\n\n"
            "**输出要求**：\n"
            "- 如果图片中没有明确的格式要求，返回空字符串\n"
            "- 如果找到格式要求，只转写格式要求部分，逐字转写，不要改写或补充\n"
            "- 不要输出解释、总结或其他无关内容\n"
            "- 优先识别和提取，确保准确性和速度"
        )

        return _call_zhipu_llm(
            prompt=prompt,
            model="glm-4v",
            temperature=0.1,
            image_url=data_url,
        )
    except Exception:
        return ""


def extract_format_from_pdf(raw: bytes, max_pages: int = 3) -> str:
    """使用智谱多模态模型直接从PDF中识别并提取格式要求。
    
    优化：将整个PDF的所有页面一次性发送给AI，让AI自行处理。
    AI可以：
    - 浏览整个PDF，自行判断哪些页面包含格式要求
    - 自动去重和合并多页的格式要求
    - 一次性处理，速度更快
    
    Args:
        raw: PDF 文件的字节数据
        max_pages: 最大检查页数，格式要求通常在前几页
    
    Returns:
        提取的格式要求文本
    """
    client = _get_zhipu_client()
    if not client:
        return ""

    try:
        # 将PDF转换为图片（AI需要图片格式）
        images = convert_from_bytes(raw, dpi=200)  # 降低DPI以加快速度
        # 只处理前几页（格式要求通常在前几页）
        if max_pages > 0:
            images = images[:max_pages]
        
        if not images:
            return ""
        
        # 将所有页面转换为base64，准备一次性发送给AI
        image_urls: list[str] = []
        for img in images:
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)  # 降低质量以减小文件大小
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{b64}"
            image_urls.append(data_url)
        
        # 一次性发送整个PDF给AI，让AI自行处理
        prompt = (
            "这是课程 syllabus 或作业说明的PDF文档（共{}页）。请识别并提取其中的【排版/格式要求】部分。\n\n"
            "**任务**：\n"
            "- 浏览所有页面，识别哪些页面包含格式要求\n"
            "- 只提取格式要求相关的内容\n"
            "- 如果多页都有格式要求，合并提取，避免重复\n\n"
            "**格式要求特征**：\n"
            "- 包含具体数值和单位（如\"12pt\"、\"2.5cm\"、\"A4\"、\"1.5倍行距\"等）\n"
            "- 描述排版样式（字体、字号、行距、页边距等）\n"
            "- 通常出现在文档开头或独立章节中\n\n"
            "**需要提取的内容**：\n"
            "- 纸张大小、页边距、字体字号、行距、标题样式、段落格式、引用格式、页眉页脚等\n\n"
            "**严格排除**：\n"
            "- 课程名称、作业题目、内容要求、字数要求、提交时间、评分标准等\n\n"
            "**输出要求**：\n"
            "- 只转写原文中的格式要求，不要改写、不要补充\n"
            "- 如果多页都有格式要求，合并输出，避免重复\n"
            "- 不要输出示例、列表格式（如\"**示例输出**\"、\"- 纸张大小\"等）\n"
            "- 不要输出解释，只转写原文内容\n"
            "- 逐字转写，保持原文表述"
        ).format(len(image_urls))

        # 一次性发送整个PDF的所有页面给AI
        content = _call_zhipu_llm(
            prompt=prompt,
            model="glm-4v",
            temperature=0.1,
            image_urls=image_urls,  # 使用多图片输入，让AI看到整个PDF
        )
        
        if not content or not content.strip():
            return ""
        
        # 清理输出：移除明显的重复标记和示例格式
        lines = content.strip().split('\n')
        cleaned_lines = []
        seen = set()
        for line in lines:
            line_stripped = line.strip()
            # 跳过空行和明显的重复标记
            if not line_stripped:
                continue
            if any(marker in line_stripped for marker in ["示例输出", "**示例", "---", "###"]):
                continue
            # 去重：跳过完全相同的行
            if line_stripped not in seen:
                seen.add(line_stripped)
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines).strip()
    except Exception:
        return ""


def extract_format_from_text_file(raw: bytes, file_type: str) -> str:
    """从文本文件（HTML/MD）中直接用AI识别格式要求。
    
    不需要先解析文本再提取，直接用AI读取文本内容并识别格式要求。
    
    Args:
        raw: 文件的字节数据
        file_type: 文件类型（.html, .htm, .md, .markdown）
    
    Returns:
        提取的格式要求文本
    """
    if not raw:
        return ""
    
    try:
        # 解码文本内容
        if file_type in {".html", ".htm"}:
            # HTML文件：提取可见文本
            html = raw.decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text("\n")
        else:
            # MD文件：直接解码
            text = raw.decode('utf-8', errors='ignore')
        
        if not text or len(text.strip()) < 10:
            return ""
        
        # 直接用AI读取文本并识别格式要求（一步到位）
        prompt = (
            "下面是一个课程 syllabus 或作业说明文档的文本内容。请**直接识别并提取**其中的【排版/格式要求】部分。\n\n"
            "**识别策略**（优先顺序）：\n"
            "- 格式要求通常出现在文档的前1-3页，特别是开头部分\n"
            "- 查找包含以下关键词的章节：\"格式要求\"、\"提交格式\"、\"排版规范\"、\"格式说明\"、\"Format Requirements\"、\"Formatting Guidelines\"等\n"
            "- 格式要求段落通常包含具体的数值和单位（如\"12pt\"、\"2.5cm\"、\"1.5倍行距\"、\"A4\"等）\n"
            "- 格式要求通常描述排版样式（字体、字号、行距、页边距等），而不是内容主题\n\n"
            "**需要提取的格式要求包括**：\n"
            "- 纸张大小（如 A4、Letter）\n"
            "- 页边距（如上2.5cm、下2.5cm、左3cm、右1.5cm，或统一页边距）\n"
            "- 字体和字号（如宋体小四、Times New Roman 12pt、黑体三号、小二号等）\n"
            "- 行距（如单倍行距、1.5倍行距、1.25倍行距、固定值22磅）\n"
            "- 标题级别与样式（如一级标题加粗居中、二级标题左对齐、标题字号等）\n"
            "- 段落格式（如首行缩进2字符、段前段后间距）\n"
            "- 引用/脚注/参考文献格式要求\n"
            "- 页眉页脚、页码格式等\n\n"
            "**严格排除以下非格式内容**：\n"
            "- 课程名称、课程介绍、课程目标、课程大纲\n"
            "- 作业题目、写作主题、内容要求、写作指导\n"
            "- 字数要求、提交时间、截止日期、提交方式\n"
            "- 评分标准、评分细则、课程安排、教学计划\n"
            "- 参考文献列表、课程资料、推荐阅读等\n\n"
            "**输出要求**：\n"
            "- 如果文档中没有明确的格式要求，返回空字符串\n"
            "- 如果找到格式要求，只提取格式要求相关的句子或段落\n"
            "- 按原文表述输出，不要改写、不要补充、不要添加解释\n"
            "- 保持格式要求的完整性和准确性\n"
            "- 优先检查文档前部内容（前3000字），格式要求通常在那里\n\n"
            f"文档内容：\n{text[:6000]}"
        )
        
        return _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1)
    
    except Exception:
        return ""


def extract_format_requirements_unified(uploaded_file) -> str:
    """统一的格式要求识别函数，所有文件类型都直接用AI识别格式要求。
    
    工作流程：
    - 图片/PDF：使用多模态AI直接识别
    - HTML/MD：直接用文本LLM读取并识别格式要求（一步到位）
    
    Args:
        uploaded_file: Streamlit上传的文件对象
    
    Returns:
        提取的格式要求文本
    """
    suffix = Path(uploaded_file.name).suffix.lower()
    file_bytes = uploaded_file.getvalue()
    
    if suffix in {".png", ".jpg", ".jpeg"}:
        # 图片文件：直接使用多模态AI
        return extract_format_from_image(file_bytes)
    
    elif suffix == ".pdf":
        # PDF文件：直接使用多模态AI
        return extract_format_from_pdf(file_bytes, max_pages=3)
    
    elif suffix in {".html", ".htm", ".md", ".markdown"}:
        # HTML/MD文件：直接用AI读取文本并识别格式要求
        return extract_format_from_text_file(file_bytes, suffix)
    
    else:
        return ""


def llm_extract_format_only(text: str) -> str:
    """从长文本中仅抽取排版/格式要求部分。"""
    if not text.strip():
        return ""

    prompt = (
        "下面是一段完整的课程 syllabus 或作业说明文档。请**快速定位并提取**其中的【排版/格式要求】部分。\n\n"
        "**定位策略**（优先顺序）：\n"
        "- 格式要求通常出现在文档的前1-3页，特别是开头部分\n"
        "- 查找包含以下关键词的章节：\"格式要求\"、\"提交格式\"、\"排版规范\"、\"格式说明\"、\"Format Requirements\"、\"Formatting Guidelines\"等\n"
        "- 如果文档很长，优先检查文档前部（前2000字），通常格式要求就在那里\n"
        "- 格式要求段落通常包含具体的数值和单位（如\"12pt\"、\"2.5cm\"、\"1.5倍\"）\n\n"
        "**需要提取的格式要求包括**：\n"
        "- 纸张大小（如 A4、Letter）\n"
        "- 页边距（如上2.5cm、下2.5cm、左3cm、右1.5cm，或统一页边距）\n"
        "- 字体和字号（如宋体小四、Times New Roman 12pt、黑体三号、小二号等）\n"
        "- 行距（如单倍行距、1.5倍行距、1.25倍行距、固定值22磅）\n"
        "- 标题级别与样式（如一级标题加粗居中、二级标题左对齐、标题字号等）\n"
        "- 段落格式（如首行缩进2字符、段前段后间距）\n"
        "- 引用/脚注/参考文献格式要求\n"
        "- 页眉页脚、页码格式等\n\n"
        "**严格排除以下非格式内容**：\n"
        "- 课程名称、课程介绍、课程目标、课程大纲\n"
        "- 作业题目、写作主题、内容要求、写作指导\n"
        "- 字数要求、提交时间、截止日期、提交方式\n"
        "- 评分标准、评分细则、课程安排、教学计划\n"
        "- 参考文献列表、课程资料、推荐阅读等\n\n"
        "**输出要求**：\n"
        "- 如果文档中没有明确的格式要求，返回空字符串\n"
        "- 如果找到格式要求，只提取格式要求相关的句子或段落\n"
        "- 按原文表述输出，不要改写、不要补充、不要添加解释\n"
        "- 保持格式要求的完整性和准确性\n\n"
        f"原文（优先检查前部内容）：\n{text[:8000]}"
    )

    return _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1)


def llm_enhance_markdown(text: str, format_requirements: str = "") -> str:
    """使用智谱 LLM 将普通文本转为带 # 标题结构的 Markdown。
    
    Args:
        text: 原始文本内容
        format_requirements: 格式要求文本（可选），用于指导标题格式识别
    """
    if not text.strip():
        return text

    format_guidance = ""
    if format_requirements and format_requirements.strip():
        format_guidance = (
            f"\n\n**格式要求参考**（如果格式要求中指定了标题样式，请参考）：\n"
            f"{format_requirements[:1000]}\n"
            f"注意：如果格式要求中提到了标题级别（如\"一级标题\"、\"二级标题\"），请按照该层级结构识别。\n"
        )

    prompt = (
        "你是一名文档排版助手。请把下面的中文报告文本转成结构清晰的 Markdown，准确识别标题层级和特殊格式。\n\n"
        "**标题识别规则**：\n"
        "- 使用 # 作为主标题（文档标题，通常只有一个）\n"
        "- 使用 ## 作为一级标题（如\"一、背景\"、\"二、分析\"、\"第一章\"、\"第一部分\"等）\n"
        "- 使用 ### 作为二级标题（如\"（一）\"、\"（二）\"、\"1.1\"、\"2.1\"、\"第一节\"等小节标题）\n"
        "- 准确识别标题的层级关系，不要混淆一级和二级标题\n"
        "- 如果文本中有明确的编号体系（如\"一、\"、\"（一）\"、\"1.\"、\"（1）\"），按照编号层级识别\n\n"
        "**特殊格式识别**：\n"
        "- 识别并保留加粗文本（使用 **文本** 标记）\n"
        "- 识别并保留列表格式（使用 - 或 1. 标记）\n"
        "- 识别并保留引用、脚注等特殊格式\n"
        "- 保留原文的段落结构和换行\n\n"
        "**内容处理**：\n"
        "- 正文用普通段落，不要添加列表编号，除非原文确实是列表\n"
        "- 保留引文、脚注等所有内容和顺序，只调整为合适的标题和段落\n"
        "- 不要添加示例，不要解释，直接输出 Markdown 内容\n"
        "- 确保标题层级准确，不要将正文误识别为标题\n"
        f"{format_guidance}"
        f"\n原始文本：\n{text[:6000]}"
    )

    content = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.2)
    if not content:
        return text

    # 有些模型会包一层 ```markdown ... ```，这里做一次剥壳
    if content.startswith("```"):
        # 去掉前三个反引号和可选的语言标记
        first_newline = content.find("\n")
        if first_newline != -1:
            inner = content[first_newline + 1 :]
            # 去掉结尾的 ```（如果存在）
            if inner.rstrip().endswith("```"):
                inner = inner.rstrip()
                inner = inner[: inner.rfind("```")]
            content = inner.strip()

    return content


def llm_segment_blocks(format_requirements: str, body: str) -> list[dict]:
    """使用智谱 LLM 直接将正文划分为 title / heading1 / heading2 / body 块，返回 JSON 列表。"""
    if not body.strip():
        return []

    format_guidance = ""
    if format_requirements and format_requirements.strip():
        format_guidance = (
            "\n\n**格式要求参考**：\n"
            "如果格式要求中提到了标题级别（如\"一级标题\"、\"二级标题\"、\"标题字号\"等），"
            "请参考这些信息来准确识别标题层级。\n"
        )

    prompt = (
        "你是一名文档排版助手，请根据【格式要求】和【正文内容】准确划分结构，输出 JSON 数组。\n"
        "每个元素必须是形如 {\"type\": \"title|heading1|heading2|body\", \"text\": \"...\"} 的对象：\n\n"
        "**标题类型说明**：\n"
        "- type 为 \"title\" 表示整篇文档主标题（通常只有一个或极少数几个，如\"管理思维课程报告\"）\n"
        "- type 为 \"heading1\" 表示一级标题（如\"一、背景介绍\"、\"二、问题分析\"、\"第一章\"、\"第一部分\"等）\n"
        "- type 为 \"heading2\" 表示二级标题（如\"（一）\"、\"（二）\"、\"1.1\"、\"2.1\"、\"第一节\"、\"第一小节\"等）\n"
        "- type 为 \"body\" 表示正文段落\n\n"
        "**识别规则**：\n"
        "- 准确识别标题的层级关系，不要混淆一级和二级标题\n"
        "- 如果文本中有明确的编号体系（如\"一、\"、\"（一）\"、\"1.\"、\"（1）\"），按照编号层级识别\n"
        "- 一级标题通常是章节标题，二级标题是章节下的小节标题\n"
        "- 如果格式要求中指定了标题格式，请参考格式要求来识别标题层级\n"
        "- 不要将正文段落误识别为标题\n"
        "- 不要改写正文内容，只拆分和标注结构\n\n"
        "**输出要求**：\n"
        "- 仅输出 JSON 数组，不要添加多余文字或解释\n"
        "- 确保 JSON 格式正确，可以被解析\n"
        f"{format_guidance}"
        f"【格式要求】:\n{format_requirements[:2000]}\n\n"
        f"【正文内容】:\n{body[:8000]}"
    )

    content = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1)
    if not content:
        return []

    data = _extract_json_from_text(content, bracket_type="[")
    if not isinstance(data, list):
        return []

    blocks: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type", "body"))
        # 支持 title, heading1, heading2, body 四种类型
        if block_type not in {"title", "heading1", "heading2", "body"}:
            block_type = "body"
        text = str(item.get("text", "")).strip()
        if text:
            blocks.append({"type": block_type, "text": text})

    return blocks


# ======================
# 格式要求解析
# ======================

def parse_format_requirements(format_text: str) -> dict[str, dict[str, object]]:
    """从格式要求文本中解析格式参数，返回格式配置字典。
    
    使用LLM从格式要求文本中提取格式参数，包括：
    - 纸张大小（A4等）
    - 页边距（上、下、左、右）
    - 字体和字号（标题、一级标题、二级标题、正文）
    - 行距
    - 首行缩进
    
    Args:
        format_text: 格式要求文本
    
    Returns:
        格式配置字典，结构与 DEFAULT_CONFIG 一致
    """
    if not format_text or not format_text.strip():
        return {}
    
    prompt = (
        "下面是一段格式要求文本。请从中提取格式参数，并以JSON格式输出。\n\n"
        "**需要提取的参数**：\n"
        "- 纸张大小（如 A4、Letter）\n"
        "- 页边距：上、下、左、右（单位：cm或厘米）\n"
        "- 标题字体和字号（如\"黑体三号\"、\"18pt\"等）\n"
        "- 一级标题字体和字号（如\"黑体四号\"、\"15pt\"等）\n"
        "- 二级标题字体和字号（如\"黑体四号\"、\"14pt\"等）\n"
        "- 正文字体和字号（如\"宋体小四\"、\"12pt\"等）\n"
        "- 行距（如\"1.5倍\"、\"1.25倍\"、\"固定值22磅\"等）\n"
        "- 首行缩进（如\"2字符\"、\"2个字符\"等）\n\n"
        "**输出格式**（JSON对象）：\n"
        "{\n"
        '  "page": {\n'
        '    "paper_size": "A4",\n'
        '    "margin_top_cm": 2.5,\n'
        '    "margin_bottom_cm": 2.5,\n'
        '    "margin_left_cm": 3.0,\n'
        '    "margin_right_cm": 1.5\n'
        "  },\n"
        '  "title": {\n'
        '    "font_cn": "黑体",\n'
        '    "size_pt": 18\n'
        "  },\n"
        '  "heading1": {\n'
        '    "font_cn": "黑体",\n'
        '    "size_pt": 15\n'
        "  },\n"
        '  "heading2": {\n'
        '    "font_cn": "黑体",\n'
        '    "size_pt": 14\n'
        "  },\n"
        '  "body": {\n'
        '    "font_cn": "宋体",\n'
        '    "size_pt": 12,\n'
        '    "line_spacing": 1.25,\n'
        '    "first_line_chars": 2\n'
        "  }\n"
        "}\n\n"
        "**说明**：\n"
        "- 如果格式要求中没有提到某个参数，该参数可以不包含在输出中\n"
        "- 字号转换：小二号≈18pt，三号≈16pt，小三号≈15pt，四号≈14pt，小四号≈12pt\n"
        "- 字体：黑体、宋体、Times New Roman等\n"
        "- 行距：如果是\"倍\"，直接输出数字（如1.5）；如果是\"固定值X磅\"，需要转换为倍数\n"
        "- 只输出JSON，不要添加解释\n\n"
        f"格式要求文本：\n{format_text[:3000]}"
    )
    
    content = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1)
    if not content:
        return {}
    
    # 提取JSON
    data = _extract_json_from_text(content, bracket_type="{")
    if not isinstance(data, dict):
        return {}
    
    # 验证和清理数据
    parsed_config: dict[str, dict[str, object]] = {}
    
    # 解析页面配置
    if "page" in data and isinstance(data["page"], dict):
        page_cfg = {}
        page_data = data["page"]
        if "paper_size" in page_data:
            page_cfg["paper_size"] = str(page_data["paper_size"])
        if "margin_top_cm" in page_data:
            try:
                page_cfg["margin_top_cm"] = float(page_data["margin_top_cm"])
            except (ValueError, TypeError):
                pass
        if "margin_bottom_cm" in page_data:
            try:
                page_cfg["margin_bottom_cm"] = float(page_data["margin_bottom_cm"])
            except (ValueError, TypeError):
                pass
        if "margin_left_cm" in page_data:
            try:
                page_cfg["margin_left_cm"] = float(page_data["margin_left_cm"])
            except (ValueError, TypeError):
                pass
        if "margin_right_cm" in page_data:
            try:
                page_cfg["margin_right_cm"] = float(page_data["margin_right_cm"])
            except (ValueError, TypeError):
                pass
        if page_cfg:
            parsed_config["page"] = page_cfg
    
    # 解析样式配置（title, heading1, heading2, body）
    for style_type in ["title", "heading1", "heading2", "body"]:
        if style_type in data and isinstance(data[style_type], dict):
            style_cfg = {}
            style_data = data[style_type]
            
            if "font_cn" in style_data:
                style_cfg["font_cn"] = str(style_data["font_cn"])
            if "font_en" in style_data:
                style_cfg["font_en"] = str(style_data["font_en"])
            if "size_pt" in style_data:
                try:
                    style_cfg["size_pt"] = float(style_data["size_pt"])
                except (ValueError, TypeError):
                    pass
            if "bold" in style_data:
                style_cfg["bold"] = bool(style_data["bold"])
            if "alignment" in style_data:
                style_cfg["alignment"] = str(style_data["alignment"])
            if "line_spacing" in style_data:
                try:
                    style_cfg["line_spacing"] = float(style_data["line_spacing"])
                except (ValueError, TypeError):
                    pass
            if "first_line_chars" in style_data:
                try:
                    style_cfg["first_line_chars"] = float(style_data["first_line_chars"])
                except (ValueError, TypeError):
                    pass
            
            if style_cfg:
                parsed_config[style_type] = style_cfg
    
    return parsed_config


def _merge_config(default_config: dict, parsed_config: dict) -> dict:
    """合并默认配置和解析的格式配置。
    
    Args:
        default_config: 默认配置
        parsed_config: 从格式要求中解析的配置
    
    Returns:
        合并后的配置
    """
    merged = {}
    
    # 合并页面配置
    if "page" in parsed_config:
        merged["page"] = {**default_config.get("page", {}), **parsed_config["page"]}
    else:
        merged["page"] = default_config.get("page", {}).copy()
    
    # 合并样式配置
    for style_type in ["title", "heading1", "heading2", "body"]:
        if style_type in parsed_config:
            merged[style_type] = {
                **default_config.get(style_type, {}),
                **parsed_config[style_type]
            }
        else:
            merged[style_type] = default_config.get(style_type, {}).copy()
    
    return merged


# ======================
# 文档生成主流程
# ======================

def _generate_document(format_requirements: str, markdown_content: str) -> bytes | None:
    """生成Word文档的主流程。
    
    Args:
        format_requirements: 格式要求文本
        markdown_content: Markdown内容文本
    
    Returns:
        生成的文档字节流，如果生成失败则返回None
    """
    try:
        # 优先：如果内容中没有任何 # 标记，直接用 LLM 划分 title / heading1 / heading2 / body
        if "#" not in markdown_content:
            blocks = llm_segment_blocks(format_requirements, markdown_content)
            if not blocks:
                # 回退到旧逻辑：先转 Markdown，再解析
                content_to_parse = llm_enhance_markdown(markdown_content, format_requirements)
                blocks = parse_markdown(content_to_parse)
        else:
            # 已有 Markdown 标记，按原规则解析
            blocks = parse_markdown(markdown_content)

        # 获取默认配置
        default_config = get_default_config()
        
        # 如果格式要求文本存在，解析并合并配置
        if format_requirements and format_requirements.strip():
            parsed_config = parse_format_requirements(format_requirements)
            if parsed_config:
                config = _merge_config(default_config, parsed_config)
            else:
                config = default_config
        else:
            config = default_config
        
        doc = generate_docx(blocks, config)
        return doc_to_bytes(doc)
    except Exception:
        return None


# Streamlit 主应用入口文件
# 串联 Markdown 解析与 Word 文档生成逻辑


def main() -> None:
    # 初始化语言（默认英文）
    if "lang" not in st.session_state:
        st.session_state["lang"] = "en"

    # 页面基础配置
    st.set_page_config(
        page_title=t("app_title"),
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # 自定义全局样式（Figma Dark 风格）
    st.markdown(
        """
        <style>
        /* UI build: 2025-12-17-02 */
        :root {
          --bg: #111217;
          --card: #1A1B22;
          --panel: #20212B;
          --border: #2E2F3A;
          --text: #EAEAEA;
          --muted: #A8A9B3;
          --accent: #7C3AED;
          --icon: #007AFF;
        }

        /* 页面淡入动画 */
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }

        html, body, [class*="css"] {
          font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
                       "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif;
          color: var(--text);
          background: var(--bg);
        }

        .main .block-container {
          animation: fadeIn 0.45s ease;
          max-width: 1280px;
          padding-top: 0.9rem;
          padding-bottom: 1.4rem;
        }

        /* 侧边栏（默认折叠） */
        [data-testid="stSidebar"] {
          background-color: #0f1014;
        }

        /* 标题（更有展示感） */
        h1 {
          background: linear-gradient(135deg, #7C3AED 0%, #A78BFA 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          letter-spacing: -0.03em;
          font-weight: 850;
          font-size: 2.2rem;
          text-shadow: 0 14px 40px rgba(0, 0, 0, 0.7);
        }

        h2, h3 {
          color: var(--text);
          letter-spacing: -0.01em;
        }

        /* 卡片（st.container(border=True)） */
        div[data-testid="stContainer"] {
          background: var(--card);
          border: 1px solid var(--border);
          border-radius: 14px;
          padding: 1.0rem 1.0rem 0.9rem 1.0rem;
          box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
        }

        /* 组件 label */
        label, [data-testid="stWidgetLabel"] > div {
          color: var(--muted) !important;
          font-weight: 600 !important;
        }

        /* 上传区（Dropzone） */
        [data-testid="stFileUploaderDropzone"] {
          border: 1px dashed var(--border);
          background: var(--panel);
          border-radius: 12px;
          padding: 0.9rem;
          transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
        }
        [data-testid="stFileUploaderDropzone"]:hover {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.16);
          transform: translateY(-1px);
        }
        [data-testid="stFileUploaderDropzone"] * {
          color: var(--text);
        }
        /* 隐藏右侧 \"Browse files\" 小按钮，只保留整块区域可点击 */
        [data-testid="stFileUploader"] button {
          display: none !important;
        }

        /* 文本框 */
        .stTextArea textarea {
          background-color: #15161c;
          border: 1px solid var(--border);
          border-radius: 12px;
          color: var(--text);
          resize: none;
          overflow-y: auto;
          font-size: 0.95rem;
          line-height: 1.55;
          transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }
        .stTextArea textarea:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.18);
        }
        .stTextArea textarea::placeholder {
          color: var(--muted);
        }

        /* 底部 CTA 按钮（只作用于底部 .cta-row，不影响教程里的按钮） */
        .cta-row [data-testid="stButton"] button,
        .cta-row [data-testid="stDownloadButton"] button {
          width: 56px !important;
          height: 56px !important;
          min-width: 56px !important;
          min-height: 56px !important;
          border-radius: 50% !important;
          padding: 0 !important;
          background: linear-gradient(135deg, #7C3AED 0%, #6D28D9 100%) !important;
          border: 1px solid rgba(255,255,255,0.08) !important;
          box-shadow: 0 10px 24px rgba(124,58,237,0.25) !important;
          font-size: 24px !important;
          font-weight: 700 !important;
          font-family: "SF Pro Display", -apple-system, BlinkMacSystemFont, sans-serif !important;
          color: white !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
          cursor: pointer !important;
          transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
        }
        .cta-row [data-testid="stButton"] button:hover,
        .cta-row [data-testid="stDownloadButton"] button:hover {
          transform: translateY(-1px);
          box-shadow: 0 16px 36px rgba(124,58,237,0.32) !important;
          filter: brightness(1.05);
        }
        .cta-row [data-testid="stButton"] button:active,
        .cta-row [data-testid="stDownloadButton"] button:active {
          transform: translateY(0px) scale(0.99);
        }
        .cta-row [data-testid="stDownloadButton"] button:disabled {
          filter: grayscale(0.15) brightness(0.9);
          opacity: 0.6;
          cursor: not-allowed !important;
        }

        /* Tutorial step */
        .tutorial-step {
          background: var(--panel);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 0.9rem;
          min-height: 92px;
        }
        .tutorial-step .t-title {
          font-weight: 750;
          color: var(--text);
          margin-bottom: 0.25rem;
        }
        .tutorial-step .t-desc {
          color: var(--muted);
          font-size: 0.92rem;
          line-height: 1.4;
        }

        /* Logo 头部区域 */
        .logo-header {
          display: flex;
          align-items: center;
          gap: 1rem;
          padding: 0.2rem 0 0.1rem 0;
        }
        .logo-header img {
          height: 100px;
          width: auto;
          object-fit: contain;
        }
        .logo-header .title-block {
          display: flex;
          flex-direction: column;
          gap: 0.15rem;
        }
        .logo-header .app-subtitle {
          font-size: 0.92rem;
          color: rgba(255,255,255,0.55);
          margin: 0;
          line-height: 1.3;
        }

        /* 顶部装饰线（标题下细渐变条） */
        .hero-divider {
          height: 2px;
          width: 100%;
          border-radius: 999px;
          background: linear-gradient(
            90deg,
            rgba(124, 58, 237, 0.0) 0%,
            rgba(124, 58, 237, 0.85) 40%,
            rgba(167, 139, 250, 0.9) 60%,
            rgba(124, 58, 237, 0.0) 100%
          );
          opacity: 0.9;
          margin: 0.2rem 0 0.3rem 0;
        }

        /* Alert 更像卡片 */
        div[data-testid="stAlert"] {
          border-radius: 12px;
          border: 1px solid var(--border);
          background: rgba(255, 255, 255, 0.03);
        }

        /* 统一的 section 标题区 */
        .section-header {
          display: flex;
          flex-direction: column;
          gap: 0.15rem;
        }

        .section-header h4 {
          margin: 0;
          color: var(--text);
          font-size: 1.0rem;
          letter-spacing: -0.01em;
        }

        .section-header .sub {
          color: var(--muted);
          font-size: 0.9rem;
          line-height: 1.35;
        }

        /* 顶部 Hero 区 */
        .app-hero {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 4px 8px 4px;
          margin-bottom: 4px;
        }

        .app-hero-left {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .app-hero-title {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .app-hero-title h1 {
          margin: 0;
          font-size: 28px;
          font-weight: 800;
          letter-spacing: -0.03em;
          background: linear-gradient(135deg, #a855f7 0%, #38bdf8 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }

        .app-hero-subtitle {
          margin: 0;
          font-size: 14px;
          color: var(--muted);
        }

        .app-hero-badge {
          padding: 4px 10px;
          border-radius: 999px;
          border: 1px solid var(--border);
          font-size: 11px;
          color: var(--muted);
        }

        /* 顶部渐变分割线（复用现有 hero-divider 名称） */
        .hero-divider {
          height: 2px;
          width: 100%;
          border-radius: 999px;
          background: linear-gradient(
            90deg,
            rgba(124, 58, 237, 0) 0%,
            rgba(124, 58, 237, 0.9) 40%,
            rgba(167, 139, 250, 0.9) 60%,
            rgba(124, 58, 237, 0) 100%
          );
          opacity: 0.95;
          margin: 0.25rem 0 0.6rem 0;
        }

        /* 主区域卡片 */
        .app-card {
          background: var(--card);
          border-radius: 16px;
          border: 1px solid var(--border);
          padding: 18px 18px 16px 18px;
          box-shadow: 0 18px 40px rgba(15, 23, 42, 0.65);
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        /* 底部操作区 */
        .app-footer {
          margin-top: 8px;
          padding: 10px 0 4px 0;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .app-footer-inner {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          padding: 8px 16px;
          border-radius: 999px;
          background: rgba(15, 23, 42, 0.9);
          border: 1px solid rgba(148, 163, 184, 0.35);
          box-shadow: 0 18px 40px rgba(15, 23, 42, 0.85);
        }

        .app-footer-status {
          font-size: 12px;
          color: var(--muted);
        }

        .app-footer [data-testid="stButton"] button,
        .app-footer [data-testid="stDownloadButton"] button {
          width: 44px !important;
          height: 44px !important;
          min-width: 44px !important;
          min-height: 44px !important;
          border-radius: 999px !important;
          padding: 0 !important;
          background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%) !important;
          border: 1px solid rgba(148, 163, 184, 0.6) !important;
          box-shadow: 0 12px 28px rgba(88, 80, 236, 0.45) !important;
          font-size: 20px !important;
          font-weight: 700 !important;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
            "Segoe UI", sans-serif !important;
          color: #f9fafb !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
        }

        .app-footer [data-testid="stButton"] button:hover,
        .app-footer [data-testid="stDownloadButton"] button:hover {
          transform-origin: center;
          transform: translateY(-1px) scale(1.02);
          box-shadow: 0 18px 40px rgba(88, 80, 236, 0.65) !important;
        }

        .app-footer [data-testid="stDownloadButton"] button:disabled {
          filter: grayscale(0.4) brightness(0.7);
          opacity: 0.6;
          cursor: not-allowed !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 侧边栏（默认折叠）：语言切换 + 帮助
    with st.sidebar:
        st.title(t("sidebar_title"))

        lang = st.radio(
            "Language / 语言",
            options=["en", "zh"],
            index=0 if st.session_state["lang"] == "en" else 1,
            format_func=lambda v: "English" if v == "en" else "简体中文",
        )
        if lang != st.session_state["lang"]:
            st.session_state["lang"] = lang
            st.rerun()

        if st.button(t("tutorial_button") + " ▶", use_container_width=True):
            st.session_state["show_tutorial"] = True
            st.rerun()

        st.markdown(f"- {t('sidebar_step1')}")
        st.markdown(f"- {t('sidebar_step2')}")
        st.markdown(f"- {t('sidebar_step3')}")

    # 初始化 session_state，用于在上传文件后填充文本框
    if "format_requirements" not in st.session_state:
        st.session_state["format_requirements"] = ""
    if "markdown_content" not in st.session_state:
        st.session_state["markdown_content"] = ""
    if "show_tutorial" not in st.session_state:
        st.session_state["show_tutorial"] = True
    if "doc_bytes" not in st.session_state:
        st.session_state["doc_bytes"] = None

    # 首屏 Tutorial（简化版：居中卡片，不再真正虚化背景，保证交互稳定）
    if st.session_state["show_tutorial"]:
        st.write("")  # 轻微上边距
        with st.container(border=True):
            st.markdown(f"### {t('tutorial_title')}")
            st.caption(t("subtitle"))

            s1, s2, s3 = st.columns(3, gap="medium")
            with s1:
                st.markdown(
                    '<div class="tutorial-step">'
                    f'<div class="t-title">{t("tutorial_step1_title")}</div>'
                    f'<div class="t-desc">{t("tutorial_step1_desc")}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
            with s2:
                st.markdown(
                    '<div class="tutorial-step">'
                    f'<div class="t-title">{t("tutorial_step2_title")}</div>'
                    f'<div class="t-desc">{t("tutorial_step2_desc")}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
            with s3:
                st.markdown(
                    '<div class="tutorial-step">'
                    f'<div class="t-title">{t("tutorial_step3_title")}</div>'
                    f'<div class="t-desc">{t("tutorial_step3_desc")}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("")  # 间距
            c1, c2, c3 = st.columns([3, 4, 3])
            with c2:
                if st.button(t("tutorial_button"), type="primary", use_container_width=True, key="tutorial_start"):
                    st.session_state["show_tutorial"] = False
                    st.rerun()

        # 只显示教程卡片，其余界面不渲染
        st.stop()

    # 顶部 Hero（只在 tutorial 关闭后显示）- 带 Logo
    logo_path = Path(__file__).parent / "Logo.png"
    if logo_path.exists():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
        logo_src = f"data:image/png;base64,{logo_b64}"
    else:
        logo_src = ""

    st.markdown(
        f"""
        <div class="app-hero">
          <div class="app-hero-left">
            {'<img src="' + logo_src + '" alt="Doc logo" style="width:40px;height:40px;border-radius:12px;object-fit:cover;background:#020617;" />' if logo_src else ''}
            <div class="app-hero-title">
              <h1>Doc. – AI Format Assistant</h1>
              <p class="app-hero-subtitle">{t('subtitle')}</p>
            </div>
          </div>
          <div class="app-hero-badge">
            for MBA · academic writing
          </div>
        </div>
        <div class="hero-divider"></div>
        """,
        unsafe_allow_html=True,
    )

    # 左右两列：左“格式要求”，右“内容”
    col_left, col_right = st.columns([5, 7], gap="large")

    # ===== 左列：格式要求 =====
    with col_left:
        st.markdown('<div class="app-card">', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="section-header">
              <h4>{t('section_format')}</h4>
            </div>
            """,
            unsafe_allow_html=True,
        )

        format_file = st.file_uploader(
            t("uploader_format_label"),
            type=["pdf", "png", "jpg", "jpeg", "html", "htm", "md", "markdown"],
            key="format_file",
            label_visibility="collapsed",
            help=t("uploader_format_help"),
        )

        if format_file is not None:
            suffix = Path(format_file.name).suffix.lower()
            
            # 如果是图片文件，显示预览
            if suffix in {".png", ".jpg", ".jpeg"}:
                image_bytes = format_file.getvalue()
                st.image(image_bytes, caption=t("image_preview_caption"), use_column_width=True)
            
            # 统一使用AI识别格式要求（所有文件类型）
            with st.spinner(t("spinner_recognizing_image")):
                recognized = extract_format_requirements_unified(format_file)
            
            if recognized:
                st.session_state["format_requirements"] = recognized
                st.success(t("success_format_recognized"))
            else:
                st.warning(t("warn_image_not_recognized"))

        format_requirements = st.text_area(
            "format_requirements_text",
            placeholder=t("format_text_placeholder"),
            height=220,
            value=st.session_state["format_requirements"],
            label_visibility="collapsed",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # ===== 右列：内容（Markdown） =====
    with col_right:
        st.markdown('<div class="app-card">', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="section-header">
              <h4>{t('section_content')}</h4>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 内容侧：支持上传 Markdown 文件（与左侧格式区风格一致）
        content_file = st.file_uploader(
            t("content_uploader_label"),
            type=["md", "markdown"],
            key="content_file",
            help=t("content_uploader_help"),
            label_visibility="collapsed",
        )
        if content_file is not None:
            _, md_text = parse_uploaded_file(content_file)
            if md_text:
                st.session_state["markdown_content"] = md_text

        markdown_content = st.text_area(
            "content_text",
            placeholder=t("content_text_placeholder"),
            height=260,
            value=st.session_state["markdown_content"],
            label_visibility="collapsed",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # 如无需要，可不额外增加底部留白

    # 底部居中 CTA：状态提示 + 圆形生成 + 图标下载
    st.markdown('<div class="app-footer"><div class="app-footer-inner">', unsafe_allow_html=True)

    has_doc = st.session_state.get("doc_bytes") is not None
    status_text = ""
    if not st.session_state.get("markdown_content", "").strip():
        status_text = "Step 2 · Paste your markdown to enable Generate"
    elif not has_doc:
        status_text = "Ready to generate your Word document"
    else:
        status_text = "✅ Document ready · click ↓ to download"

    st.markdown(f'<span class="app-footer-status">{status_text}</span>', unsafe_allow_html=True)

    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        gen_clicked = st.button("➕", type="primary", key="generate_doc")

    with btn_col2:
        st.download_button(
            label="⬇",
            data=st.session_state["doc_bytes"] if has_doc else b"",
            file_name="formatted_document.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            disabled=not has_doc,
            key="download_doc",
        )

    st.markdown("</div></div>", unsafe_allow_html=True)

    if gen_clicked:
        # 重置旧的文档
        st.session_state["doc_bytes"] = None

        if not markdown_content.strip():
            st.warning(t("warn_need_content"))
        else:
            with st.spinner(t("spinner_generating")):
                doc_bytes = _generate_document(format_requirements, markdown_content)
                if doc_bytes:
                    st.session_state["doc_bytes"] = doc_bytes
                    st.success(t("success_generated"))
                    # 重新渲染页面，使下载按钮立即可用
                    st.rerun()
                else:
                    st.error(t("error_generating") + "Failed to generate document.")


if __name__ == "__main__":
    main()

