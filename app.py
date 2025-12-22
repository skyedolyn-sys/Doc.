import base64
import json
import os
import re
from io import BytesIO
from pathlib import Path

import streamlit as st
import pdfplumber
import pytesseract
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pdf2image import convert_from_bytes
from PIL import Image, ImageOps
from zhipuai import ZhipuAI
from typing import Optional, List
from format_parser import get_default_config, parse_markdown
from doc_generator import generate_docx, doc_to_bytes

# 加载 .env 文件中的环境变量（容错：解析错误不应中断应用）
try:
    load_dotenv()
except Exception:
    # 如果 .env 解析失败，不要中断应用；在 Cloud 上优先使用 Streamlit Secrets
    pass


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
    """获取 ZhipuAI 客户端。优先从 Streamlit Secrets 读取，再回退到环境变量。"""
    api_key = None
    # 优先尝试从 Streamlit Secrets 读取（在 Streamlit Cloud 中设置）
    try:
        if hasattr(st, "secrets") and st.secrets.get("ZHIPU_API_KEY"):
            api_key = st.secrets.get("ZHIPU_API_KEY")
    except Exception:
        # 忽略 secrets 读取错误（不要暴露异常）
        pass

    # 回退到环境变量（本地开发或 CI）
    if not api_key:
        api_key = os.getenv("ZHIPU_API_KEY")

    if not api_key:
        # 仅显示存在性提示，不要输出密钥本身
        try:
            st.warning("ZHIPU API key not found. Please set ZHIPU_API_KEY in Streamlit Secrets.")
        except Exception:
            pass
        return None

    return ZhipuAI(api_key=api_key)


def debug_key_presence():
    """临时调试函数：显示 key 是否存在于 env 或 st.secrets（不显示 key 值）。"""
    try:
        env_present = bool(os.getenv("ZHIPU_API_KEY"))
        secret_present = False
        try:
            secret_present = bool(st.secrets.get("ZHIPU_API_KEY"))
        except Exception:
            secret_present = False
        try:
            st.text(f"ZHIPU_API_KEY in env: {env_present}, in st.secrets: {secret_present}")
        except Exception:
            # 在某些导入阶段可能没有 UI，上面不应抛出
            pass
    except Exception:
        pass


def _call_zhipu_llm(
    prompt: str,
    model: str = "glm-4-flash",
    temperature: float = 0.1,
    image_url: Optional[str] = None,
    image_urls: Optional[List[str]] = None,
    timeout: int = 30,
    max_retries: int = 2,
) -> str:
    """通用ZhipuAI LLM调用函数。
    
    Args:
        prompt: 文本提示
        model: 模型名称，默认为 "glm-4-flash"
        temperature: 温度参数，默认为 0.1
        image_url: 可选的单张图片URL（用于多模态调用）
        image_urls: 可选的多张图片URL列表（用于一次性处理整个PDF）
        timeout: 超时时间（秒），默认30秒
        max_retries: 最大重试次数，默认2次
    
    Returns:
        模型返回的文本内容，如果调用失败则返回空字符串
    """
    client = _get_zhipu_client()
    if not client:
        return ""
    
    for attempt in range(max_retries + 1):
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
                timeout=timeout,
            )
            content = (resp.choices[0].message.content or "").strip()
            return content
        except Exception as e:
            if attempt < max_retries:
                import time
                time.sleep(1)  # 等待1秒后重试
                continue
            else:
                import streamlit as st
                st.warning(f"LLM调用失败（已重试{max_retries}次）: {str(e)[:100]}")
                return ""
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
                timeout=60,  # 多模态模型需要更长时间
            )
            if content:
                page_texts.append(content)

        return "\n\n".join(page_texts).strip()
    except Exception:
        return ""


def extract_format_from_image(raw: bytes) -> str:
    """使用智谱多模态模型从格式要求截图中提取文字（侧重排版/格式描述）。"""
    def _local_ocr_from_bytes(raw_bytes: bytes) -> str:
        """Use local pytesseract (with simple preprocessing) to extract text from image bytes."""
        try:
            img = Image.open(BytesIO(raw_bytes)).convert("L")  # convert to grayscale
            img = ImageOps.autocontrast(img)
            # upscale to improve OCR on low-res images
            img = img.resize((int(img.width * 2), int(img.height * 2)), Image.BILINEAR)
            text = pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 3")
            return text.strip()
        except Exception:
            return ""

    # 1) Prefer remote multimodal OCR if client exists; otherwise, fallback to local OCR
    client = _get_zhipu_client()
    if not client:
        try:
            st.warning("ZHIPU_API_KEY not set — using local Tesseract OCR fallback.")
        except Exception:
            pass
        return _local_ocr_from_bytes(raw)

    # 2) Prepare image for remote multimodal call
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

        content = _call_zhipu_llm(
            prompt=prompt,
            model="glm-4v",
            temperature=0.1,
            image_url=data_url,
            timeout=60,  # 多模态模型需要更长时间
        )

        # Debug: show short preview of remote output
        try:
            st.write("DEBUG: multimodal returned (short):", repr(content)[:1000])
        except Exception:
            pass

        # If remote returned nothing, fallback to local OCR
        if not content or not content.strip():
            fallback = _local_ocr_from_bytes(raw)
            try:
                st.info("Remote OCR returned empty — used local Tesseract fallback.")
                st.write("🔍 local OCR (first 2000 chars):", repr(fallback)[:2000])
            except Exception:
                pass
            return fallback

        return content
    except Exception:
        # final safety: attempt local OCR before giving up
        return _local_ocr_from_bytes(raw)


def _clean_format_output(content: str) -> str:
    """清理格式要求输出，移除解释性文字和重复内容。"""
    if not content or not content.strip():
        return ""
    
    lines = content.strip().split('\n')
    cleaned_lines = []
    seen = set()
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        # 检查是否包含格式关键词
        has_format_keyword = any(fmt_marker in line_stripped for fmt_marker in [
            # 中文格式关键词
            "pt", "cm", "倍", "行距", "字体", "字号", "页边距", 
            "缩进", "对齐", "加粗", "居中", "A4", "Letter",
            "宋体", "黑体", "Times", "Roman", "Calibri",
            # 英文格式关键词
            "spacing", "margin", "font", "size", "alignment", "indent",
            "bold", "italic", "center", "left", "right", "justify",
            "header", "footer", "page number", "citation", "reference",
            "APA", "MLA", "Chicago", "double", "single", "inch", "inches",
            "Times New Roman", "Calibri", "Arial", "Helvetica"
        ])
        
        # 跳过解释性文字
        if any(marker in line_stripped for marker in [
            "示例输出", "**示例", "---", "###", 
            "以下是", "提取结果", "识别结果",
            "**注意**", "**注意", "注意：", "注意",
            "由于", "无法", "需要您", "需要你", "因此",
            "清晰度", "问题", "实际操作", "细致", "阅读", "标注"
        ]):
            if not has_format_keyword:
                continue
        
        # 检查是否是解释性提示
        explanation_patterns = [
            r'^\*\*注意\*\*.*',
            r'^注意：.*',
            r'.*由于.*清晰度.*问题.*',
            r'.*无法.*识别.*',
            r'.*需要您.*',
            r'.*需要你.*',
            r'.*实际操作.*',
            r'.*细致.*阅读.*标注.*'
        ]
        is_explanation = any(re.match(pattern, line_stripped) for pattern in explanation_patterns)
        if is_explanation and not has_format_keyword:
            continue
        
        # 对于包含"第"、"页"的行，需要更谨慎处理
        if any(marker in line_stripped for marker in ["第", "页", "页面", "Page", "PAGE"]):
            is_page_marker_only = (
                re.match(r'^第\s*\d+\s*页\s*$', line_stripped) or 
                re.match(r'^Page\s*\d+\s*$', line_stripped, re.IGNORECASE) or
                re.match(r'^页面\s*\d+\s*$', line_stripped)
            )
            if is_page_marker_only and not has_format_keyword:
                continue
        
        # 去重
        if line_stripped not in seen:
            seen.add(line_stripped)
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines).strip()


def normalize_ocr_text(text: str) -> str:
    """简单修正常见的 OCR/模型识别错误并做少量规范化，返回清洗后的文本。"""
    if not text:
        return text
    s = text

    # 常见错字映射（可按需添加）
    replacements = {
        r"\\bdbuble\\b": "double",
        r"\\bdbuble-?\\s*spac(?:ed|e)?\\b": "double-spaced",
        r"\\bouble-?spaced\\b": "double-spaced",
        r"\\bDuble-?spaced\\b": "double-spaced",
        r"\\bPage\\s*:\\s*": "Page: ",
        r"\\bLength\\s*:\\s*": "Length: ",
        r"\\b1\\.27cm\\b": "1.27cm",
        # 英文常见连字符/空格问题
        r"(\\b[0-9]+)\\s+pt\\b": r"\\1pt",
    }
    for pat, rep in replacements.items():
        try:
            s = re.sub(pat, rep, s, flags=re.IGNORECASE)
        except Exception:
            pass

    # 修正常见 OCR 引起的重复空格/非ascii可见字符
    s = re.sub(r"[ \\t]{2,}", " ", s)
    s = re.sub(r"\\uFFFD", "", s)  # 删除替换字符
    s = s.strip()
    return s


def extract_format_from_pdf(raw: bytes, max_pages: int = 5) -> str:
    """使用智谱多模态模型逐页识别并提取格式要求。
    
    采用逐页处理策略，确保每一页都被独立检查，不会遗漏任何格式要求。
    
    Args:
        raw: PDF 文件的字节数据
        max_pages: 最大检查页数，格式要求通常在前几页（默认5页）
    
    Returns:
        提取的格式要求文本
    """
    client = _get_zhipu_client()
    if not client:
        return ""

    try:
        # 将PDF转换为图片（AI需要图片格式）
        images = convert_from_bytes(raw, dpi=200)
        if max_pages > 0:
            images = images[:max_pages]
        
        if not images:
            return ""
        
        all_format_texts = []
        total_pages = len(images)
        
        # 逐页处理，确保每一页都被独立检查
        for page_idx, img in enumerate(images, 1):
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{b64}"
            
            prompt = (
                f"这是PDF文档的第{page_idx}页（共{total_pages}页）。请检查这一页是否包含【排版/格式要求】。\n\n"
                "**任务**：\n"
                "- 判断这一页是否包含格式要求\n"
                "- 如果包含格式要求，提取所有格式要求内容，并明确区分中文格式要求和英文格式要求\n"
                "- 如果不包含格式要求，返回空字符串\n\n"
                "**格式要求的识别与区分标准**：\n"
                "- **中文格式要求**（适用于中文文本）：包含中文描述或中文格式术语，如\"1.5倍行距\"、\"宋体小四\"、\"黑体三号\"、\"首行缩进2字符\"、\"段前段后间距\"、\"左对齐\"、\"居中\"等\n"
                "- **英文格式要求**（适用于英文文本）：包含英文描述或英文格式术语，如\"double spacing\"、\"Times New Roman\"、\"1-inch margins\"、\"APA 7th edition\"、\"centered\"、\"bold\"、\"left-aligned\"、\"first-line indent\"等\n"
                "- 通用格式要素（中英文都要识别）：字体、字号（如\"12pt\"、\"2.5cm\"、\"A4\"）、行距、页边距、对齐方式、缩进、标题格式、引用格式（APA、MLA、Chicago等）、页眉页脚、页码格式等\n\n"
                "**提取规则**：\n"
                "- **必须同时识别和提取中文格式要求和英文格式要求**，不能遗漏任何一种语言\n"
                "- 如果格式要求明确指定了适用的语言（如\"中文部分：...\"、\"English text: ...\"、\"For Chinese: ...\"、\"For English: ...\"），必须保留这些语言区分标记\n"
                "- 如果格式要求没有明确指定语言，根据格式描述的语种判断：中文描述=中文格式要求，英文描述=英文格式要求\n"
                "- 保持原文语言，不要翻译格式要求\n\n"
                "**严格排除的内容**（不要提取）：\n"
                "- 课程名称、课程介绍、课程目标\n"
                "- 作业题目、写作主题、内容要求\n"
                "- 字数要求、提交时间、截止日期\n"
                "- 评分标准、评分细则、课程安排\n"
                "- 参考文献列表、课程资料等非格式内容\n\n"
                "**输出要求**：\n"
                "- 如果同时包含中英文格式要求，保持原文的排列顺序，或先中文后英文\n"
                "- 如果格式要求明确区分了适用语言，保留这些区分标记（如\"中文部分\"、\"English section\"等）\n"
                "- 只输出格式要求文本，不要添加解释、总结或前后缀\n"
                "- **绝对不要输出任何解释性文字**，如\"注意\"、\"由于\"、\"无法识别\"等\n"
                "- 如果这一页没有格式要求，返回空字符串"
            )
            
            content = _call_zhipu_llm(
                prompt=prompt,
                model="glm-4v",
                temperature=0.1,
                image_url=data_url,
                timeout=60,  # 多模态模型需要更长时间
            )
            
            if content and content.strip():
                # 清理这一页的输出
                cleaned_content = _clean_format_output(content)
                if cleaned_content:
                    all_format_texts.append(cleaned_content)
        
        # 合并所有页面的格式要求
        return '\n\n'.join(all_format_texts).strip()
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
        
        return _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1, timeout=30)
    
    except Exception:
        return ""


# ======================
# 常用格式库
# ======================

FORMAT_TEMPLATES = {
    "APA 7th Edition": """纸张大小：A4
页边距：上下左右均为2.54cm（1英寸）
字体：Times New Roman 12pt（英文）或宋体小四（中文）
行距：双倍行距（double spacing）
标题格式：
- 一级标题：加粗居中，首字母大写
- 二级标题：加粗左对齐，首字母大写
- 三级标题：加粗缩进，首字母大写，句末加句号
段落格式：首行不缩进，段落之间空一行
引用格式：作者-日期格式（Author-Date），如 (Smith, 2020)
参考文献：悬挂缩进0.5英寸，按作者姓氏字母顺序排列
页眉：标题（前50个字符），右对齐
页码：右上角，从标题页开始编号""",

    "MLA 9th Edition": """纸张大小：Letter（8.5 x 11英寸）或A4
页边距：上下左右均为2.54cm（1英寸）
字体：Times New Roman 12pt
行距：双倍行距（double spacing）
标题格式：无特殊格式要求，标题居中
段落格式：首行缩进0.5英寸（1.27cm）
引用格式：作者-页码格式，如 (Smith 45)
参考文献：标题为"Works Cited"，悬挂缩进0.5英寸，按作者姓氏字母顺序排列
页眉：右上角显示姓氏和页码，如 Smith 1
页码：从第一页开始编号""",

    "Chicago 17th Edition": """纸张大小：Letter或A4
页边距：上下左右均为2.54cm（1英寸）
字体：Times New Roman 12pt
行距：双倍行距（double spacing）
标题格式：标题居中，加粗
段落格式：首行缩进0.5英寸（1.27cm）
引用格式：脚注或尾注格式，如 ¹ 或 [1]
参考文献：标题为"Bibliography"或"Works Cited"，悬挂缩进0.5英寸
页眉：无特殊要求
页码：从第一页开始编号，右上角或底部居中""",

    "IEEE": """纸张大小：Letter或A4
页边距：上下2.54cm，左右1.91cm（0.75英寸）
字体：Times New Roman 10pt
行距：单倍行距（single spacing）
标题格式：
- 一级标题：14pt，加粗，左对齐，大写
- 二级标题：12pt，加粗，左对齐
- 三级标题：10pt，加粗，左对齐，斜体
段落格式：首行不缩进，段落之间空一行
引用格式：数字引用格式，如 [1], [2-5]
参考文献：标题为"References"，按引用顺序编号
页眉：无特殊要求
页码：从第一页开始编号""",

    "GB/T 7714-2015（中文）": """纸张大小：A4
页边距：上下2.5cm，左右3cm
字体：中文使用宋体，英文使用Times New Roman；正文小四号（12pt）
行距：1.5倍行距
标题格式：
- 一级标题：黑体三号，居中
- 二级标题：黑体四号，左对齐
- 三级标题：黑体小四号，左对齐
段落格式：首行缩进2字符
引用格式：作者-出版年格式，如（张三，2020）
参考文献：标题为"参考文献"，悬挂缩进，按引用顺序编号
页眉：无特殊要求
页码：底部居中，从正文开始编号"""
}


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
        return extract_format_from_pdf(file_bytes, max_pages=5)
    
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

    content = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.2, timeout=30)
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


def llm_segment_blocks_chunked(format_requirements: str, body: str, chunk_size: int = 6000, overlap: int = 500) -> list[dict]:
    """使用分块策略处理长文档的标题识别。
    
    Args:
        format_requirements: 格式要求文本
        body: 正文内容（可能很长）
        chunk_size: 每个分块的最大字符数（默认6000，留出prompt空间）
        overlap: 分块之间的重叠字符数（默认500，避免在标题中间切分）
    
    Returns:
        合并后的 blocks 列表
    """
    if not body.strip():
        return []
    
    all_blocks: list[dict] = []
    total_length = len(body)
    position = 0
    
    format_guidance = ""
    if format_requirements and format_requirements.strip():
        format_guidance = (
            "\n\n**格式要求参考**：\n"
            "如果格式要求中提到了标题级别（如\"一级标题\"、\"二级标题\"、\"标题字号\"等），"
            "请参考这些信息来准确识别标题层级。\n"
        )
    
    # 基础 prompt 模板
    base_prompt_template = (
        "你是一名文档排版助手，请根据【格式要求】和【正文内容片段】准确划分结构，输出 JSON 数组。\n"
        "每个元素必须是形如 {\"type\": \"title|heading1|heading2|body\", \"text\": \"...\"} 的对象：\n\n"
        "**标题类型**：\n"
        "- title: 文档主标题（通常只有一个）\n"
        "- heading1: 一级标题（如\"一、\"、\"二、\"、\"第一章\"、\"1.\"等）\n"
        "- heading2: 二级标题（如\"（一）\"、\"(一)\"、\"1.1\"、\"1）\"等）\n"
        "- body: 正文段落\n\n"
        "**识别与标记规则（必须严格遵守）**：\n"
        "- **重要**：即使没有Markdown标记（`#`），也要识别纯文本格式的标题（\"一、\"、\"（一）\"、\"(一)\"、\"1.1\"等），并做相应标记，确保文档生成时根据格式要求进行处理；\n"
        "- **编号识别与标记**：\n"
        "  * heading1: \"一、\"、\"二、\"、\"第一章\"、\"1.\"等开头的独立行，**必须标记为heading1**\n"
        "  * heading2: \"（一）\"、\"(一)\"、\"1.1\"、\"1）\"等开头的独立行（无论中文括号还是英文括号），**必须标记为heading2**\n"
        "- **关键规则**：\n"
        "  * 以\"（一）\"、\"(一)\"、\"1.1\"、\"1）\"等编号开头的行，**必须标记为heading2，绝对不能标记为body**\n"
        "  * 嵌套编号层级：\"一、\"→heading1，\"（一）\"/(一)→heading2\n"
        "  * 不要把带编号的标题标记为body\n"
        "- **识别验证与标记确认**：\n"
        "  * 识别到标题后，必须立即标记为对应的type（title/heading1/heading2），不能遗漏或错误标记\n"
        "  * 如果格式要求中指定了标题格式，参考格式要求来识别和标记标题层级\n"
        "  * 只拆分和标注结构，不改写内容\n\n"
        "**示例**：\n"
        "- \"一、事件概况\" → {\"type\": \"heading1\", \"text\": \"一、事件概况\"}\n"
        "- \"(一)目标定位\" → {\"type\": \"heading2\", \"text\": \"(一)目标定位\"}\n\n"
        "**输出要求**：\n"
        "- 仅输出 JSON 数组，不要添加多余文字或解释；\n"
        "- 确保 JSON 格式正确，可以被解析；\n"
        "- 每个识别到的标题都必须有正确的type标记，确保文档生成时能根据格式要求进行处理。\n"
        f"{format_guidance}"
        f"【格式要求】:\n{format_requirements[:2000]}\n\n"
    )
    
    chunk_index = 0
    total_chunks = (total_length + chunk_size - 1) // chunk_size  # 估算总块数
    
    # 创建进度条
    import streamlit as st
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    while position < total_length:
        # 计算当前分块的结束位置
        end_position = min(position + chunk_size, total_length)
        chunk_text = body[position:end_position]
        
        # 如果不是最后一个分块，尝试在句号、换行或标题后切分，避免在标题中间切分
        if end_position < total_length:
            # 向后查找合适的切分点（句号、换行、标题标记等）
            lookahead = min(overlap, total_length - end_position)
            for i in range(lookahead):
                check_pos = end_position + i
                if check_pos >= total_length:
                    break
                char = body[check_pos]
                # 在句号、换行、标题编号后切分
                if char in ['。', '.', '\n']:
                    # 检查是否是标题编号后的句号
                    if i > 0:
                        prev_chars = body[max(0, check_pos-3):check_pos]
                        if any(marker in prev_chars for marker in ['一、', '二、', '三、', '（一）', '（二）', '1.', '2.', '3.']):
                            end_position = check_pos + 1
                            chunk_text = body[position:end_position]
                            break
                    else:
                        end_position = check_pos + 1
                        chunk_text = body[position:end_position]
                        break
        
        # 构建当前分块的 prompt
        context_info = ""
        if chunk_index > 0:
            context_info = f"\n**注意**：这是文档的第 {chunk_index + 1} 个片段（共约 {total_chunks} 个片段，前面已有 {chunk_index} 个片段处理完成）。"
            context_info += "如果片段开头是正文段落（没有标题），说明它是上一个片段的延续，请保持类型为 \"body\"。\n"
        
        prompt = base_prompt_template + context_info + f"【正文内容片段】:\n{chunk_text}"
        
        # 更新进度条
        progress = (chunk_index + 1) / total_chunks
        progress_bar.progress(progress)
        status_text.text(f"正在处理文档片段 {chunk_index + 1}/{total_chunks}...")
        
        # 调用 LLM 处理当前分块
        try:
            content = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1, timeout=30)
            
            if content:
                data = _extract_json_from_text(content, bracket_type="[")
                if isinstance(data, list):
                    # 处理当前分块的 blocks
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        block_type = str(item.get("type", "body"))
                        if block_type not in {"title", "heading1", "heading2", "body"}:
                            block_type = "body"
                        text = str(item.get("text", "")).strip()
                        if text:
                            all_blocks.append({"type": block_type, "text": text})
            else:
                # 如果当前分块处理失败，至少保留原始文本作为body
                if chunk_text.strip():
                    all_blocks.append({"type": "body", "text": chunk_text.strip()})
        except Exception as e:
            # 如果处理当前分块时出错，记录错误但继续处理下一个分块
            import streamlit as st
            st.warning(f"处理片段 {chunk_index + 1} 时出错: {str(e)[:100]}，跳过该片段")
            # 至少保留原始文本
            if chunk_text.strip():
                all_blocks.append({"type": "body", "text": chunk_text.strip()})
        
        # 移动到下一个分块（考虑重叠）
        new_position = end_position - overlap if end_position < total_length else end_position
        # 防止死循环：确保position总是向前移动
        if new_position > position:
            position = new_position
        else:
            # 如果position没有增加，强制推进
            position = end_position
        chunk_index += 1
        
        # 防止无限循环：如果处理的分块数过多，强制结束
        if chunk_index > 100:  # 最多处理100个分块
            st.warning(f"文档过长，已处理前100个片段，剩余内容将作为正文处理")
            if position < total_length:
                remaining_text = body[position:].strip()
                if remaining_text:
                    all_blocks.append({"type": "body", "text": remaining_text})
            break
    
    # 清除进度条
    progress_bar.empty()
    status_text.empty()
    
    # 后处理：合并相邻的相同类型的 body 块
    merged_blocks: list[dict] = []
    for i, block in enumerate(all_blocks):
        if i > 0 and block.get("type") == "body" and merged_blocks and merged_blocks[-1].get("type") == "body":
            # 合并相邻的 body 块
            merged_blocks[-1]["text"] += "\n" + block.get("text", "")
        else:
            merged_blocks.append(block)
    
    return merged_blocks


def llm_segment_blocks(format_requirements: str, body: str) -> list[dict]:
    """使用智谱 LLM 直接将正文划分为 title / heading1 / heading2 / body 块，返回 JSON 列表。
    
    对于长文档（>8000字符），自动使用分块处理策略。
    """
    # 如果文档较长，使用分块处理
    if len(body) > 8000:
        return llm_segment_blocks_chunked(format_requirements, body)
    
    # 原有逻辑（短文档）
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
        "**标题类型**：\n"
        "- title: 文档主标题（通常只有一个）\n"
        "- heading1: 一级标题（如\"一、\"、\"二、\"、\"第一章\"、\"1.\"等）\n"
        "- heading2: 二级标题（如\"（一）\"、\"(一)\"、\"1.1\"、\"1）\"等）\n"
        "- body: 正文段落\n\n"
        "**识别与标记规则（必须严格遵守）**：\n"
        "- **重要**：即使没有Markdown标记（`#`），也要识别纯文本格式的标题（\"一、\"、\"（一）\"、\"(一)\"、\"1.1\"等），并做相应标记，确保文档生成时根据格式要求进行处理；\n"
        "- **编号识别与标记**：\n"
        "  * heading1: \"一、\"、\"二、\"、\"第一章\"、\"1.\"等开头的独立行，**必须标记为heading1**\n"
        "  * heading2: \"（一）\"、\"(一)\"、\"1.1\"、\"1）\"等开头的独立行（无论中文括号还是英文括号），**必须标记为heading2**\n"
        "- **关键规则**：\n"
        "  * 以\"（一）\"、\"(一)\"、\"1.1\"、\"1）\"等编号开头的行，**必须标记为heading2，绝对不能标记为body**\n"
        "  * 嵌套编号层级：\"一、\"→heading1，\"（一）\"/(一)→heading2\n"
        "  * 不要把带编号的标题标记为body\n"
        "- **识别验证与标记确认**：\n"
        "  * 识别到标题后，必须立即标记为对应的type（title/heading1/heading2），不能遗漏或错误标记\n"
        "  * 如果格式要求中指定了标题格式，参考格式要求来识别和标记标题层级\n"
        "  * 只拆分和标注结构，不改写内容\n\n"
        "**示例**：\n"
        "- \"一、事件概况\" → {\"type\": \"heading1\", \"text\": \"一、事件概况\"}\n"
        "- \"(一)目标定位\" → {\"type\": \"heading2\", \"text\": \"(一)目标定位\"}\n\n"
        "**输出要求**：\n"
        "- 仅输出 JSON 数组，不要添加多余文字或解释；\n"
        "- 确保 JSON 格式正确，可以被解析；\n"
        "- 每个识别到的标题都必须有正确的type标记，确保文档生成时能根据格式要求进行处理。\n"
        f"{format_guidance}"
        f"【格式要求】:\n{format_requirements[:2000]}\n\n"
        f"【正文内容】:\n{body[:8000]}"
    )

    content = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1, timeout=30)
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

def _detect_format_template(format_text: str) -> str:
    """检测格式文本中是否包含格式库关键词。
    
    Args:
        format_text: 格式要求文本
    
    Returns:
        格式库名称，如果未检测到则返回空字符串
    """
    if not format_text:
        return ""
    
    format_lower = format_text.lower()
    
    # 检测格式库关键词
    template_keywords = {
        "APA 7th Edition": ["apa", "apa 7th", "apa 7", "american psychological association"],
        "MLA 9th Edition": ["mla", "mla 9th", "mla 9", "modern language association"],
        "Chicago 17th Edition": ["chicago", "chicago 17th", "chicago 17", "turabian"],
        "IEEE": ["ieee"],
        "GB/T 7714-2015（中文）": ["gb/t 7714", "gb/t7714", "gb/t 7714-2015", "国标7714", "国标 7714"]
    }
    
    for template_name, keywords in template_keywords.items():
        if any(kw in format_lower for kw in keywords):
            return template_name
    
    return ""


def parse_format_requirements(format_text: str) -> dict[str, dict[str, object]]:
    """从格式要求文本中解析格式参数，返回格式配置字典。
    
    如果检测到格式库关键词，优先使用格式库配置。
    否则使用LLM从格式要求文本中提取格式参数，包括：
    - 纸张大小（A4等）
    - 页边距（上、下、左、右）
    - 字体和字号（标题、一级标题、二级标题、正文）
    - 行距
    - 首行缩进（会根据文档类型自动调整）
    
    Args:
        format_text: 格式要求文本
    
    Returns:
        格式配置字典，结构与 DEFAULT_CONFIG 一致
    """
    if not format_text or not format_text.strip():
        return {}
    
    # 关键修复：优先检测格式库
    template_name = _detect_format_template(format_text)
    if template_name:
        # 如果检测到格式库，直接使用格式库配置（通过LLM解析格式库文本）
        template_text = FORMAT_TEMPLATES.get(template_name, "")
        if template_text:
            # 使用格式库文本进行解析
            format_text = template_text
    
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
        "- 首行缩进（如\"2字符\"、\"2个字符\"、\"0.5英寸\"、\"0\"等）\n\n"
        "**首行缩进规则**（重要）：\n"
        "- 如果格式要求中明确提到\"首行缩进\"、\"first-line indent\"等，使用指定的值\n"
        "- 如果格式要求中提到英文格式（如\"Times New Roman\"、\"English\"、\"APA\"、\"MLA\"等），且未明确指定首行缩进，使用 4.5（对应0.5英寸）\n"
        "- 如果格式要求中提到中文格式（如\"宋体\"、\"黑体\"、\"GB/T\"等），且未明确指定首行缩进，使用 2（2字符）\n"
        "- 如果格式要求中未明确指定，且无法判断文档类型，不要包含 first_line_chars 字段（让后续逻辑根据字体判断）\n\n"
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
    
    content = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.1, timeout=30)
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


def _merge_config(default_config: dict, parsed_config: dict, format_text: str = "") -> dict:
    """合并默认配置和解析的格式配置。
    
    Args:
        default_config: 默认配置
        parsed_config: 从格式要求中解析的配置
        format_text: 格式要求文本（可选，用于智能检测文档类型）
    
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
    # 关键修复：对于 body，先排除 first_line_chars，单独处理
    for style_type in ["title", "heading1", "heading2", "body"]:
        if style_type in parsed_config:
            if style_type == "body":
                # body 特殊处理：先合并其他字段，排除 first_line_chars
                merged[style_type] = default_config.get(style_type, {}).copy()
                parsed_style = parsed_config[style_type]
                for key, value in parsed_style.items():
                    if key != "first_line_chars":  # first_line_chars 单独处理
                        merged[style_type][key] = value
            else:
                # 其他样式类型正常合并
                merged[style_type] = {
                    **default_config.get(style_type, {}),
                    **parsed_config[style_type]
                }
        else:
            # 关键修复：对于 body，即使 parsed_config 中没有，也要排除 first_line_chars
            if style_type == "body":
                merged[style_type] = default_config.get(style_type, {}).copy()
                # 立即删除 first_line_chars，避免污染
                if "first_line_chars" in merged[style_type]:
                    del merged[style_type]["first_line_chars"]
            else:
                merged[style_type] = default_config.get(style_type, {}).copy()
    
    # 智能处理正文首行缩进
    # 关键修复：从合并后的配置中获取，但 first_line_chars 需要单独处理
    body_cfg = merged.get("body", {}) or {}
    
    # 重要：确保 body_cfg 中没有从默认配置继承的 first_line_chars
    # 如果解析配置中没有明确指定，删除它
    parsed_body = parsed_config.get("body", {})
    if "first_line_chars" in body_cfg:
        if not (isinstance(parsed_body, dict) and "first_line_chars" in parsed_body):
            del body_cfg["first_line_chars"]
    
    # 直接检查解析配置中是否明确指定了首行缩进
    # 注意：这里检查的是 parsed_config，而不是合并后的 merged
    parsed_body = parsed_config.get("body", {})
    parsed_indent = None
    if isinstance(parsed_body, dict) and "first_line_chars" in parsed_body:
        try:
            parsed_indent = float(parsed_body["first_line_chars"])
        except (TypeError, ValueError):
            pass
    
    # 如果解析配置中明确指定了首行缩进，需要验证是否合理
    if parsed_indent is not None:
        # 如果值是2或0（可能是LLM返回的默认值），需要验证是否适合当前文档
        if (parsed_indent == 2.0 or parsed_indent == 0) and format_text:
            # 检查是否是英文文档
            format_lower = format_text.lower()
            font_cn = str(body_cfg.get("font_cn", "")).lower()
            is_chinese_font = font_cn in ["宋体", "黑体", "微软雅黑", "仿宋", "楷体"]
            
            # 检测英文关键词（包含学术格式和商业文档关键词，统一处理为英文文档）
            english_keywords = ["times new roman", "arial", "calibri", "english", 
                               "double spacing", "single spacing", "inch", "pt", "point",
                               "apa", "mla", "chicago", "ieee", "harvard", "vancouver",
                               "business", "report", "proposal", "memo", "letter"]
            has_english = any(kw in format_lower for kw in english_keywords)
            
            # 关键修复：优先根据字体判断，而不是仅依赖关键词检测
            if not is_chinese_font and font_cn:
                # 非中文字体（且字体已设置）：统一使用4.5字符（0.5英寸）
                body_cfg["first_line_chars"] = 4.5
            elif is_chinese_font:
                # 中文字体：使用2字符
                body_cfg["first_line_chars"] = 2.0
            elif has_english and not is_chinese_font:
                # 如果检测到英文关键词且不是中文字体，统一使用4.5字符（0.5英寸）
                body_cfg["first_line_chars"] = 4.5
            else:
                # 无法确定：根据字体判断（优先字体）
                if font_cn and font_cn not in ["宋体", "黑体", "微软雅黑", "仿宋", "楷体"]:
                    # 非中文字体：统一使用4.5字符
                    body_cfg["first_line_chars"] = 4.5
                else:
                    # 中文字体或未设置：使用解析值
                    body_cfg["first_line_chars"] = parsed_indent
        else:
            # 其他值（4.5等）直接使用
            body_cfg["first_line_chars"] = parsed_indent
        
        merged["body"] = body_cfg
        return merged
    
    # 如果解析配置中没有指定首行缩进，根据格式要求文本智能检测
    if format_text:
        format_lower = format_text.lower()
        
        # 关键修复：优先根据字体判断
        font_cn = str(body_cfg.get("font_cn", "")).lower()
        is_chinese_font = font_cn in ["宋体", "黑体", "微软雅黑", "仿宋", "楷体"]
        
        # 检测中文格式关键词
        chinese_keywords = ["宋体", "黑体", "gb/t", "国标", "中文", "小四", "四号", "三号"]
        
        # 检测英文格式关键词（用于判断是否为英文文档）
        # 包含学术格式和商业文档关键词，统一处理为英文文档
        english_keywords = ["times new roman", "arial", "calibri", "english", 
                           "double spacing", "single spacing", "inch", "pt", "point",
                           "apa", "mla", "chicago", "ieee", "harvard", "vancouver",
                           "business", "report", "proposal", "memo", "letter"]
        
        has_chinese = any(kw in format_lower for kw in chinese_keywords)
        has_english = any(kw in format_lower for kw in english_keywords)
        
        if is_chinese_font:
            # 中文字体：2字符缩进（优先字体判断）
            body_cfg["first_line_chars"] = 2.0
        elif not is_chinese_font and font_cn:
            # 非中文字体（且字体已设置）：统一使用4.5字符（0.5英寸）
            body_cfg["first_line_chars"] = 4.5
        elif has_chinese:
            # 中文格式关键词：2字符缩进
            body_cfg["first_line_chars"] = 2.0
        elif has_english and not has_chinese:
            # 英文文档（统一）：4.5字符缩进（0.5英寸）
            body_cfg["first_line_chars"] = 4.5
        else:
            # 无法确定：根据字体判断
            if font_cn in ["宋体", "黑体", "微软雅黑", "仿宋", "楷体"]:
                # 中文字体：2字符缩进
                body_cfg["first_line_chars"] = 2.0
            else:
                # 英文字体：统一使用4.5字符（0.5英寸）
                body_cfg["first_line_chars"] = 4.5
    else:
        # 没有格式要求文本：根据字体判断
        font_cn = str(body_cfg.get("font_cn", "")).lower()
        if font_cn in ["宋体", "黑体", "微软雅黑", "仿宋", "楷体"]:
            # 中文字体：2字符缩进
            body_cfg["first_line_chars"] = 2.0
        else:
            # 英文字体：统一使用4.5字符（0.5英寸）
            body_cfg["first_line_chars"] = 4.5
    
    # 关键修复：确保 body_cfg 中总是有 first_line_chars 值（包括0）
    # 这样即使配置传递有问题，也不会回退到默认值2
    merged["body"] = body_cfg
    return merged


# ======================
# 预览和格式调整
# ======================

def _generate_preview_info(blocks: list[dict], config: dict) -> dict:
    """生成文档预览信息，用于用户确认。
    
    Args:
        blocks: 文档块列表
        config: 格式配置
    
    Returns:
        包含文档结构摘要和格式配置的字典
    """
    title_count = sum(1 for b in blocks if b.get("type") == "title")
    heading1_count = sum(1 for b in blocks if b.get("type") == "heading1")
    heading2_count = sum(1 for b in blocks if b.get("type") == "heading2")
    body_count = sum(1 for b in blocks if b.get("type") == "body")
    
    # 提取前几个标题作为预览
    preview_titles = []
    for b in blocks[:10]:  # 只显示前10个块
        if b.get("type") in {"title", "heading1", "heading2"}:
            text = b.get("text", "")
            preview_titles.append({
                "type": b.get("type"),
                "text": text[:50] + "..." if len(text) > 50 else text
            })
    
    return {
        "structure": {
            "title_count": title_count,
            "heading1_count": heading1_count,
            "heading2_count": heading2_count,
            "body_count": body_count,
            "preview_titles": preview_titles,
        },
        "format": {
            "page": config.get("page", {}),
            "title": config.get("title", {}),
            "heading1": config.get("heading1", {}),
            "heading2": config.get("heading2", {}),
            "body": config.get("body", {}),
        }
    }


def _apply_format_adjustment(format_requirements: str, adjustment_request: str, history: list) -> str:
    """根据用户反馈调整格式要求。
    
    Args:
        format_requirements: 原始格式要求文本
        adjustment_request: 用户的调整请求（如"标题字号太小，改成18pt"）
        history: 之前的对话历史
    
    Returns:
        调整后的格式要求文本
    """
    history_text = ""
    if history:
        recent_history = history[-3:]  # 只保留最近3轮
        history_text = "\n".join([
            f"用户: {h.get('user', '')}\nAI: {h.get('ai', '')}" 
            for h in recent_history if isinstance(h, dict)
        ])
    
    prompt = (
        "你是一名文档格式调整助手。用户提供了原始格式要求，并提出了调整需求。"
        "请根据用户的需求，生成更新后的格式要求文本。\n\n"
        "**原始格式要求**：\n"
        f"{format_requirements}\n\n"
        "**用户调整需求**：\n"
        f"{adjustment_request}\n\n"
    )
    
    if history_text:
        prompt += (
            "**对话历史**（最近3轮）：\n"
            f"{history_text}\n\n"
        )
    
    prompt += (
        "**任务**：\n"
        "- 理解用户的调整需求\n"
        "- 在原始格式要求的基础上进行修改\n"
        "- 只输出更新后的格式要求文本，不要添加解释\n"
        "- 保持格式要求的完整性和准确性\n"
        "- 如果用户需求不明确，保持原格式要求不变"
    )
    
    adjusted = _call_zhipu_llm(prompt=prompt, model="glm-4-flash", temperature=0.2, timeout=30)
    return adjusted.strip() if adjusted else format_requirements


# ======================
# 文档生成主流程
# ======================

def _generate_document(format_requirements: str, markdown_content: str) -> tuple[bytes | None, dict | None]:
    """生成Word文档的主流程。
    
    Args:
        format_requirements: 格式要求文本
        markdown_content: Markdown内容文本
    
    Returns:
        (生成的文档字节流, 预览信息) 元组，如果生成失败则返回 (None, None)
    """
    try:
        import time
        
        blocks: list[dict]
        
        # 检查是否有Markdown标记（#、##、###）或中文编号格式标题
        # 这样可以确保上传的Markdown文件和直接粘贴的文本都能正确识别标题
        import re
        
        has_markdown_headers = any(
            line.strip().startswith(('#', '##', '###'))
            for line in markdown_content.split('\n')
            if line.strip()
        )
        
        # 检查是否有中文编号格式的标题
        has_chinese_headers = any(
            re.match(r'^[一二三四五六七八九十]+[、.]', line.strip()) or
            re.match(r'^第[一二三四五六七八九十]+[章节部分]', line.strip()) or
            re.match(r'^\d+[、.]', line.strip()) or
            re.match(r'^[（(][一二三四五六七八九十]+[）)]', line.strip()) or
            re.match(r'^\d+\.\d+', line.strip()) or
            re.match(r'^\d+[）)]', line.strip())
            for line in markdown_content.split('\n')
            if line.strip()
        )
        
        if has_markdown_headers or has_chinese_headers:
            # 如果有Markdown标记或中文编号格式，使用增强的parse_markdown解析
            # parse_markdown现在可以同时识别两种格式
            st.info("正在识别文档结构...")
            start_time = time.time()
            
            parsed_blocks = parse_markdown(markdown_content)
            # 转换为统一格式
            blocks = [
                {
                    "type": block.get("type", "body"),
                    "text": block.get("text", "").strip()
                }
                for block in parsed_blocks
                if block.get("text", "").strip()
            ]
            
            elapsed_time = time.time() - start_time
            if elapsed_time > 0.1:
                st.write(f"⏱️ 结构识别耗时: {elapsed_time:.2f}秒")
        else:
            # 如果既没有Markdown标记也没有中文编号格式，使用LLM识别
            doc_length = len(markdown_content)
            if doc_length > 8000:
                st.info(f"文档较长（{doc_length}字符），正在分块处理，请稍候...")
            else:
                st.info("正在识别文档结构...")
            
            start_time = time.time()
            blocks = llm_segment_blocks(format_requirements, markdown_content)
            elapsed_time = time.time() - start_time
            st.write(f"⏱️ 结构识别耗时: {elapsed_time:.1f}秒")
            
            # 如果LLM识别失败，回退到parse_markdown（可能文本中有未检测到的格式）
            if not blocks:
                parsed_blocks = parse_markdown(markdown_content)
                blocks = [
                    {
                        "type": block.get("type", "body"),
                        "text": block.get("text", "").strip()
                    }
                    for block in parsed_blocks
                    if block.get("text", "").strip()
                ]
        
        # 调试输出：显示识别结果统计
        if blocks:
            block_types = {}
            for b in blocks:
                b_type = b.get("type", "unknown")
                block_types[b_type] = block_types.get(b_type, 0) + 1
            st.write(f"🔍 识别结果统计: {block_types}")

        # 对 blocks 做一次统一规范与结构修正（保证至少有一个 title）
        def _normalize_blocks(raw_blocks: list[dict]) -> list[dict]:
            normalized: list[dict] = []
            for item in raw_blocks:
                if not isinstance(item, dict):
                    continue
                block_type = str(item.get("type", "body"))
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                if block_type not in {"title", "heading1", "heading2", "body"}:
                    block_type = "body"
                normalized.append({"type": block_type, "text": text})

            # 如果没有显式 title，则将第一个 heading1/heading2 提升为 title
            has_title = any(b.get("type") == "title" for b in normalized)
            if not has_title:
                for b in normalized:
                    if b.get("type") in {"heading1", "heading2"}:
                        b["type"] = "title"
                        break
            return normalized

        blocks = _normalize_blocks(blocks)

        # 获取默认配置
        default_config = get_default_config()
        
        # 如果格式要求文本存在，解析并合并配置
        if format_requirements and format_requirements.strip():
            parsed_config = parse_format_requirements(format_requirements)
            if parsed_config:
                config = _merge_config(default_config, parsed_config, format_requirements)
                # 调试：显示最终配置的首行缩进值
                body_indent = config.get("body", {}).get("first_line_chars", "未设置")
                body_font = config.get("body", {}).get("font_cn", "未设置")
                st.write(f"🔧 调试信息 - 首行缩进: {body_indent}, 字体: {body_font}")
            else:
                config = default_config
        else:
            config = default_config
        
        # 如果用户通过 UI 确认了自动解析的配置，则优先合并该确认配置
        confirmed_cfg = st.session_state.get("format_confirmed_config")
        if isinstance(confirmed_cfg, dict):
            try:
                # 确保 config 已存在
                if "page" not in config:
                    config["page"] = {}
                if "title" not in config:
                    config["title"] = {}
                if "heading1" not in config:
                    config["heading1"] = {}
                if "heading2" not in config:
                    config["heading2"] = {}
                if "body" not in config:
                    config["body"] = {}

                # Merge page-level settings
                for k, v in confirmed_cfg.get("page", {}).items():
                    config["page"][k] = v

                # Merge title/body specific settings
                for section in ("title", "heading1", "heading2", "body"):
                    sec_vals = confirmed_cfg.get(section, {})
                    if isinstance(sec_vals, dict):
                        for k, v in sec_vals.items():
                            config.setdefault(section, {})[k] = v
                st.write("✅ Using user-confirmed format configuration for generation.")
            except Exception:
                # 不要中断主流程，继续使用现有 config
                pass

        # 生成预览信息
        preview_info = _generate_preview_info(blocks, config)
        
        doc = generate_docx(blocks, config)
        doc_bytes = doc_to_bytes(doc)
        return doc_bytes, preview_info
    except Exception:
        return None, None


# Streamlit 主应用入口文件
# 串联 Markdown 解析与 Word 文档生成逻辑


def main() -> None:
    # 初始化语言（默认英文）
    if "lang" not in st.session_state:
        st.session_state["lang"] = "en"
    # 显示 key 存在性（仅调试用）
    try:
        debug_key_presence()
    except Exception:
        pass

    # 页面基础配置
    st.set_page_config(
        page_title=t("app_title"),
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # 自定义全局样式（Minimalist Stepped Flow）
    st.markdown(
        """
        <style>
        /* UI build: Minimalist Stepped Flow - 2025-01-XX */
        :root {
          --bg: #0D0D0D;
          --card: #1A1B1E;
          --panel: #1A1B1E;
          --border: #2D2E32;
          --text: #EAEAEA;
          --muted: rgba(234, 234, 234, 0.6);
          --accent: #7C3AED;
          --icon: #007AFF;
        }

        /* 页面淡入动画 */
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }

        html, body, [class*="css"] {
          font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
                       "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif;
          color: var(--text);
          background: var(--bg);
          background-image: radial-gradient(circle at 20% 50%, rgba(124, 58, 237, 0.05) 0%, transparent 50%),
                            radial-gradient(circle at 80% 80%, rgba(124, 58, 237, 0.03) 0%, transparent 50%);
        }

        .main .block-container {
          animation: fadeIn 0.45s ease;
          max-width: 960px;
          margin: 0 auto;
          padding-top: 0.9rem;
          padding-bottom: 1.4rem;
          padding-right: 0;
          padding-left: 0;
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
          font-weight: 500 !important;
          font-family: "Inter", system-ui, sans-serif !important;
        }

        /* 上传区（Dropzone） */
        [data-testid="stFileUploaderDropzone"] {
          border: 1px dashed var(--border);
          background: var(--panel);
          border-radius: 12px;
          padding: 0.9rem;
          transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.15s ease;
        }
        [data-testid="stFileUploaderDropzone"]:hover {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.3),
                      0 0 20px rgba(124, 58, 237, 0.5);
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
          padding: 16px 4px 12px 4px;
          margin-bottom: 6px;
        }

        .app-hero-left {
          display: flex;
          align-items: center;
          gap: 20px;
        }

        .app-hero-logo {
          width: 88px !important;
          height: 88px !important;
          min-width: 88px !important;
          min-height: 88px !important;
          border-radius: 16px;
          object-fit: contain !important;
          background: #020617;
          flex-shrink: 0;
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
          /* 隐藏视觉样式 */
          background: transparent;
          border: none;
          border-radius: 0;
          box-shadow: none;
          /* 保留布局属性 */
          display: flex;
          flex-direction: column;
          gap: 12px;
          /* 保留内边距以维持间距 */
          padding: 0;
        }

        /* 步骤容器 */
        .step-container {
          animation: slideIn 0.3s ease-out;
        }

        @keyframes slideIn {
          from {
            opacity: 0;
            transform: translateX(20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        /* 步骤指示器 */
        .step-indicator {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 12px;
          padding: 8px 16px;
        }

        .step-item {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 14px;
          color: var(--muted);
          transition: color 0.2s ease;
        }

        .step-item.active {
          color: var(--text);
          font-weight: 600;
        }

        .step-item-number {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 24px;
          height: 24px;
          border-radius: 50%;
          background: var(--border);
          color: var(--muted);
          font-size: 12px;
          font-weight: 600;
          transition: all 0.2s ease;
        }

        .step-item.active .step-item-number {
          background: var(--accent);
          color: white;
        }

        .step-connector {
          width: 40px;
          height: 1px;
          background: var(--border);
          margin: 0 4px;
        }

        /* Header 三列布局 */
        .app-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 4px 12px 4px;
          margin-bottom: 6px;
        }

        .header-left {
          display: flex;
          align-items: center;
          flex: 0 0 auto;
        }

        .header-logo-text {
          font-size: 24px;
          font-weight: 700;
          color: var(--text);
          letter-spacing: 0.02em;
          font-family: "Inter", system-ui, sans-serif;
          margin: 0;
          padding: 0;
        }

        .header-center {
          display: flex;
          align-items: center;
          justify-content: center;
          flex: 1 1 auto;
        }

        .header-right {
          display: flex;
          align-items: center;
          gap: 12px;
          flex: 0 0 auto;
        }

        .header-badge {
          padding: 4px 10px;
          border-radius: 999px;
          border: 1px solid var(--border);
          font-size: 11px;
          color: var(--muted);
        }

        .deploy-button {
          padding: 6px 14px;
          border-radius: 8px;
          border: 1px solid var(--border);
          background: var(--card);
          color: var(--text);
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .deploy-button:hover {
          background: var(--panel);
          border-color: var(--accent);
        }

        .header-search-icon {
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 8px;
          border: 1px solid var(--border);
          background: var(--card);
          cursor: pointer;
          transition: all 0.2s ease;
          color: var(--text);
          font-size: 16px;
        }

        .header-search-icon:hover {
          background: var(--panel);
          border-color: var(--accent);
        }

        /* 步骤导航按钮 */
        .step-nav-button {
          width: 100%;
          margin-top: 16px;
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
          gap: 8px;
          /* 隐藏视觉样式 */
          padding: 0;
          border-radius: 0;
          background: transparent;
          border: none;
          box-shadow: none;
        }

        .app-footer-status {
          font-size: 12px;
          color: var(--muted);
        }

        /* 按钮容器：让按钮紧挨着 */
        .app-footer-buttons {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          margin-left: 8px;
        }

        .app-footer [data-testid="stButton"] button,
        .app-footer [data-testid="stDownloadButton"] button,
        .app-footer-buttons [data-testid="stButton"] button,
        .app-footer-buttons [data-testid="stDownloadButton"] button {
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
        .app-footer [data-testid="stDownloadButton"] button:hover,
        .app-footer-buttons [data-testid="stButton"] button:hover,
        .app-footer-buttons [data-testid="stDownloadButton"] button:hover {
          transform-origin: center;
          transform: translateY(-1px) scale(1.02);
          box-shadow: 0 18px 40px rgba(88, 80, 236, 0.65) !important;
        }

        .app-footer [data-testid="stDownloadButton"] button:disabled,
        .app-footer-buttons [data-testid="stDownloadButton"] button:disabled {
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
    if "current_step" not in st.session_state:
        st.session_state["current_step"] = 1
    if "last_format_file_id" not in st.session_state:
        st.session_state["last_format_file_id"] = ""
    if "last_selected_format" not in st.session_state:
        st.session_state["last_selected_format"] = ""
    if "doc_preview_mode" not in st.session_state:
        st.session_state["doc_preview_mode"] = False
    if "doc_preview_info" not in st.session_state:
        st.session_state["doc_preview_info"] = None
    if "format_adjustment_history" not in st.session_state:
        st.session_state["format_adjustment_history"] = []

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

    # 顶部 Header（只在 tutorial 关闭后显示）- 三列布局
    current_step = st.session_state.get("current_step", 1)

    st.markdown(
        f"""
        <div class="app-header">
          <div class="header-left">
            <div class="header-logo-text">DOC.</div>
            </div>
          <div class="header-center">
            <div class="step-indicator">
              <div class="step-item {'active' if current_step == 1 else ''}">
                <div class="step-item-number">1</div>
                <span>Format Settings</span>
          </div>
              <div class="step-connector"></div>
              <div class="step-item {'active' if current_step == 2 else ''}">
                <div class="step-item-number">2</div>
                <span>Content Input</span>
              </div>
            </div>
          </div>
          <div class="header-right">
            <div class="header-search-icon" onclick="alert('Search functionality coming soon')" title="Search">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M7 12C9.76142 12 12 9.76142 12 7C12 4.23858 9.76142 2 7 2C4.23858 2 2 4.23858 2 7C2 9.76142 4.23858 12 7 12Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M10.5 10.5L14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <button class="deploy-button" onclick="alert('Deploy functionality coming soon')">Deploy</button>
          </div>
        </div>
        <div class="hero-divider"></div>
        """,
        unsafe_allow_html=True,
    )

    # 单列居中布局，根据步骤显示内容
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
    
    current_step = st.session_state.get("current_step", 1)
    
    if current_step == 1:
        # Step 1: Format Requirements
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
            # 计算当前文件的简单 ID（名称 + 大小），用于避免重复识别
            file_id = f"{format_file.name}_{getattr(format_file, 'size', 0)}"
            is_new_file = file_id != st.session_state.get("last_format_file_id", "")
            
            # 如果是图片文件，显示预览
            if suffix in {".png", ".jpg", ".jpeg"}:
                image_bytes = format_file.getvalue()
                # use `width` (pixels) instead of deprecated use_column_width
                st.image(image_bytes, caption=t("image_preview_caption"), width=700)
            
            if is_new_file:
                # 仅在新文件时调用 AI 识别，避免重复耗时操作
                with st.spinner(t("spinner_recognizing_image")):
                    recognized = extract_format_requirements_unified(format_file)
                
                # 临时调试输出：显示 AI 原始识别结果（便于排查为空或被清洗）
                try:
                    st.write("🔍 raw AI output (first 2000 chars):", repr(recognized)[:2000])
                except Exception:
                    # 在某些环境中 st.write 对象可能会抛错，忽略以防影响主流程
                    pass
                
                st.session_state["last_format_file_id"] = file_id
                if recognized:
                    # 先做简单清洗再存储到 session
                    cleaned_text = normalize_ocr_text(recognized)
                    st.session_state["format_requirements"] = cleaned_text
                    # 同步到格式文本框的内部 key 并触发重渲染，确保控件立即显示识别结果
                    try:
                        st.session_state["format_requirements_input"] = cleaned_text
                        st.experimental_rerun()
                    except Exception:
                        pass
                    st.success(t("success_format_recognized"))

                    # 如果是图片文件，先清洗文本再解析为结构化配置，并展示为可编辑表单供用户确认
                    if suffix in {".png", ".jpg", ".jpeg"}:
                        try:
                            parsed_cfg = parse_format_requirements(cleaned_text)
                            if parsed_cfg:
                                st.session_state["parsed_format_config"] = parsed_cfg

                                # 在 UI 中展示可编辑的解析结果，用户确认后应用到 format_confirmed_config
                                with st.expander("📄 Parsed format (review & edit)", expanded=True):
                                    st.write("Below are the fields auto-extracted from the image. Edit if needed, then click Apply.")
                                    page_cfg = parsed_cfg.get("page", {})
                                    title_cfg = parsed_cfg.get("title", {})
                                    body_cfg = parsed_cfg.get("body", {})

                                    col1, col2 = st.columns(2)
                                    with col1:
                                        page_size = st.text_input("Paper size", value=str(page_cfg.get("paper_size", "A4")))
                                        margin_top = st.text_input("Top margin (cm)", value=str(page_cfg.get("margin_top_cm", "")))
                                        margin_bottom = st.text_input("Bottom margin (cm)", value=str(page_cfg.get("margin_bottom_cm", "")))
                                    with col2:
                                        margin_left = st.text_input("Left margin (cm)", value=str(page_cfg.get("margin_left_cm", "")))
                                        margin_right = st.text_input("Right margin (cm)", value=str(page_cfg.get("margin_right_cm", "")))
                                        body_font = st.text_input("Body font (cn)", value=str(body_cfg.get("font_cn", "")))

                                    title_size = st.text_input("Title size (pt)", value=str(title_cfg.get("size_pt", "")))
                                    body_size = st.text_input("Body size (pt)", value=str(body_cfg.get("size_pt", "")))
                                    body_first_line = st.text_input("Body first_line_chars", value=str(body_cfg.get("first_line_chars", "")))

                                    if st.button("Apply parsed config", key=f"apply_parsed_{file_id}"):
                                        confirmed = {"page": {}, "title": {}, "body": {}}
                                        if page_size:
                                            confirmed["page"]["paper_size"] = page_size
                                        try:
                                            if margin_top:
                                                confirmed["page"]["margin_top_cm"] = float(margin_top)
                                            if margin_bottom:
                                                confirmed["page"]["margin_bottom_cm"] = float(margin_bottom)
                                            if margin_left:
                                                confirmed["page"]["margin_left_cm"] = float(margin_left)
                                            if margin_right:
                                                confirmed["page"]["margin_right_cm"] = float(margin_right)
                                        except Exception:
                                            st.warning("One of the margin values couldn't be parsed; please use numbers (cm).")

                                        if title_size:
                                            try:
                                                confirmed["title"]["size_pt"] = float(title_size)
                                            except Exception:
                                                pass
                                        if body_font:
                                            confirmed["body"]["font_cn"] = body_font
                                        if body_size:
                                            try:
                                                confirmed["body"]["size_pt"] = float(body_size)
                                            except Exception:
                                                pass
                                        if body_first_line:
                                            try:
                                                confirmed["body"]["first_line_chars"] = float(body_first_line)
                                            except Exception:
                                                pass

                                        st.session_state["format_confirmed_config"] = confirmed
                                        st.success("Parsed configuration applied — will be used for generation.")
                        except Exception:
                            st.warning("Automatic parsing of extracted image text failed.")
                else:
                    st.warning(t("warn_image_not_recognized"))
                    # 识别失败时，显示常用格式库选择器
                    st.info("💡 未识别到格式要求，您可以从常用格式库中选择：")
                    selected_format = st.selectbox(
                        "选择常用格式",
                        options=[""] + list(FORMAT_TEMPLATES.keys()),
                        key="format_template_selector",
                        help="选择一个常用格式模板，将自动填充到下方文本框"
                    )
                    if selected_format:
                        st.session_state["format_requirements"] = FORMAT_TEMPLATES[selected_format]
                        st.success(f"已加载 {selected_format} 格式模板")
                        st.rerun()

        # 即使没有上传文件，也显示格式库选择器
        if not format_file:
            st.info("💡 提示：您可以上传格式文件，或从常用格式库中选择：")
            selected_format = st.selectbox(
                "选择常用格式",
                options=[""] + list(FORMAT_TEMPLATES.keys()),
                key="format_template_selector_no_file",
                help="选择一个常用格式模板，将自动填充到下方文本框"
            )
            if selected_format and selected_format != st.session_state.get("last_selected_format", ""):
                st.session_state["format_requirements"] = FORMAT_TEMPLATES[selected_format]
                st.session_state["last_selected_format"] = selected_format
                st.success(f"已加载 {selected_format} 格式模板")
                st.rerun()

        format_requirements = st.text_area(
            "format_requirements_text",
            placeholder=t("format_text_placeholder"),
            height=300,
            value=st.session_state.get("format_requirements", ""),
            label_visibility="collapsed",
            key="format_requirements_input",
        )
        # Streamlit自动更新session_state，但为了确保兼容性，手动同步
        st.session_state["format_requirements"] = format_requirements
        
        st.markdown("</div>", unsafe_allow_html=True)

        # Next button
        if st.button("Next: Input Content →", type="primary", use_container_width=True, key="next_to_content"):
            st.session_state["current_step"] = 2
            st.rerun()
    
    else:
        # Step 2: Content Input
        if st.button("← Back", key="back_to_format"):
            st.session_state["current_step"] = 1
            st.rerun()
        
        st.markdown('<div class="app-card">', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="section-header">
              <h4>{t('section_content')}</h4>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 内容侧：支持上传 Markdown 文件
        content_file = st.file_uploader(
            t("content_uploader_label"),
            type=["md", "markdown"],
            key="content_file",
            help=t("content_uploader_help"),
            label_visibility="collapsed",
        )
        if content_file is not None:
            _, md_text = parse_uploaded_file(content_file)
            # Debug: show whether parsing returned content
            try:
                st.write("DEBUG: uploaded md parsed length:", len(md_text or ""))
            except Exception:
                pass

            if md_text:
                st.session_state["markdown_content"] = md_text
                # Ensure the text_area widget (key=markdown_content_input) shows the uploaded content
                try:
                    st.session_state["markdown_content_input"] = md_text
                    # Force rerun so the widget reflects the new value immediately
                    st.experimental_rerun()
                except Exception:
                    pass
            else:
                # Fallback: some Streamlit UploadedFile objects work better with getvalue()
                try:
                    raw = content_file.getvalue()
                    if isinstance(raw, (bytes, bytearray)):
                        alt = None
                        for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
                            try:
                                alt = raw.decode(enc)
                                if alt and alt.strip():
                                    break
                            except Exception:
                                continue
                        if alt and alt.strip():
                            st.session_state["markdown_content"] = alt
                            try:
                                st.session_state["markdown_content_input"] = alt
                                st.experimental_rerun()
                            except Exception:
                                pass
                            try:
                                st.info("Uploaded markdown decoded using fallback encoding.")
                            except Exception:
                                pass
                except Exception:
                    pass

        markdown_content = st.text_area(
            "content_text",
            placeholder=t("content_text_placeholder"),
            height=400,
            value=st.session_state.get("markdown_content", ""),
            label_visibility="collapsed",
            key="markdown_content_input",
        )
        # Streamlit自动更新session_state，但为了确保兼容性，手动同步
        st.session_state["markdown_content"] = markdown_content
        
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    # 底部居中操作区：生成 + 下载
    st.markdown('<div class="app-footer"><div class="app-footer-inner app-footer-buttons">', unsafe_allow_html=True)

    has_doc = st.session_state.get("doc_bytes") is not None
    format_requirements = st.session_state.get("format_requirements", "")
    markdown_content = st.session_state.get("markdown_content", "")
    preview_mode = st.session_state.get("doc_preview_mode", False)

    # 如果不在预览模式，显示生成和下载按钮
    if not preview_mode:
        col_gen, col_dl = st.columns([1, 1])
        with col_gen:
            gen_clicked = st.button("Generate", type="primary", key="generate_doc", use_container_width=True)
        with col_dl:
            st.download_button(
                label="Download",
            data=st.session_state["doc_bytes"] if has_doc else b"",
            file_name="formatted_document.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            disabled=not has_doc,
            key="download_doc",
                use_container_width=True,
            )
    else:
        # 预览模式下，只显示下载按钮（确认后可用）
        gen_clicked = False
        st.download_button(
            label="Download",
            data=st.session_state["doc_bytes"] if has_doc else b"",
            file_name="formatted_document.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            disabled=not has_doc,
            key="download_doc_preview",
            use_container_width=True,
        )

    st.markdown("</div></div>", unsafe_allow_html=True)

    if gen_clicked:
        # 重置旧的文档和预览状态
        st.session_state["doc_bytes"] = None
        st.session_state["doc_preview_mode"] = False
        st.session_state["doc_preview_info"] = None

        if not markdown_content.strip():
            st.warning(t("warn_need_content"))
        else:
            with st.spinner(t("spinner_generating")):
                doc_bytes, preview_info = _generate_document(format_requirements, markdown_content)
                if doc_bytes:
                    st.session_state["doc_bytes"] = doc_bytes
                    st.session_state["doc_preview_mode"] = True
                    st.session_state["doc_preview_info"] = preview_info
                    st.success("✅ Document generated. Please review the preview below.")
                    st.rerun()
                else:
                    st.error(t("error_generating") + "Failed to generate document.")

    # 预览和确认界面
    if st.session_state.get("doc_preview_mode") and st.session_state.get("doc_bytes") and st.session_state.get("doc_preview_info"):
        st.markdown("---")
        st.markdown("### 📋 Document Preview & Adjustment")
        
        preview_info = st.session_state["doc_preview_info"]
        structure = preview_info.get("structure", {})
        format_cfg = preview_info.get("format", {})
        
        # 显示预览信息
        with st.expander("📊 Document Structure Preview", expanded=True):
            st.markdown("**Document Structure:**")
            st.info(
                f"Title: {structure.get('title_count', 0)} | "
                f"Heading1: {structure.get('heading1_count', 0)} | "
                f"Heading2: {structure.get('heading2_count', 0)} | "
                f"Body paragraphs: {structure.get('body_count', 0)}"
            )
            
            # 显示标题预览
            preview_titles = structure.get("preview_titles", [])
            if preview_titles:
                st.markdown("**Title Preview:**")
                for title_info in preview_titles[:5]:  # 只显示前5个
                    title_type = title_info.get("type", "unknown")
                    title_text = title_info.get("text", "")
                    st.text(f"[{title_type}] {title_text}")
            
            st.markdown("**Format Configuration:**")
            format_requirements_text = st.session_state.get("format_requirements", "")
            if format_requirements_text:
                st.text_area(
                    "Current Format Requirements",
                    value=format_requirements_text,
                    height=150,
                    disabled=True,
                    key="preview_format"
                )
        
        # 格式调整对话区
        st.markdown("### 💬 Format Adjustment Chat")
        st.markdown("If the document doesn't meet your requirements, describe what needs to be adjusted:")
        
        # 显示对话历史
        chat_history = st.session_state.get("format_adjustment_history", [])
        if chat_history:
            st.markdown("**Chat History:**")
            for i, msg in enumerate(chat_history[-5:]):  # 只显示最近5条
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    with st.chat_message("user"):
                        st.write(content)
                else:
                    with st.chat_message("assistant"):
                        st.write(content)
        
        # 用户输入调整需求
        user_input = st.chat_input("Describe what format adjustments you need (e.g., '标题字号太小，改成18pt')")
        
        if user_input:
            # 添加到历史
            chat_history.append({"role": "user", "content": user_input})
            st.session_state["format_adjustment_history"] = chat_history
            
            # 调用AI调整格式
            with st.spinner("Adjusting format based on your feedback..."):
                adjusted_format = _apply_format_adjustment(
                    st.session_state.get("format_requirements", ""),
                    user_input,
                    chat_history
                )
                
                # 更新格式要求
                st.session_state["format_requirements"] = adjusted_format
                
                # AI回复
                ai_reply = "已根据您的需求调整格式要求。已更新格式配置，请点击'Regenerate'重新生成文档。"
                chat_history.append({"role": "assistant", "content": ai_reply})
                st.session_state["format_adjustment_history"] = chat_history
                
                st.success("Format adjusted! Click 'Regenerate' to apply changes.")
                st.rerun()
        
        # --- AI 健康检查（临时调试区块） ---
        with st.expander("AI Health Check (debug)"):
            st.markdown("Use this to test whether the app can reach the AI backend. This is for debugging only.")
            if st.button("Run AI connectivity test"):
                client = _get_zhipu_client()
                if not client:
                    st.error("No API key available. Set ZHIPU_API_KEY in Streamlit Secrets.")
                else:
                    with st.spinner("Calling AI..."):
                        try:
                            test_prompt = "Please reply with the single word: PONG"
                            resp = _call_zhipu_llm(prompt=test_prompt, model="glm-4-flash", timeout=15, max_retries=2)
                            if resp and resp.strip():
                                st.success("AI responded")
                                st.write(resp[:1000])
                            else:
                                st.error("AI did not return a response. Check logs.")
                        except Exception as e:
                            st.error(f"AI call exception: {str(e)[:200]}")
        
        # 操作按钮
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("✅ Confirm & Download", type="primary", use_container_width=True, key="confirm_download"):
                st.session_state["doc_preview_mode"] = False
                st.success("Document ready for download!")
                st.rerun()
        with col2:
            if st.button("🔄 Regenerate", use_container_width=True, key="regenerate_doc"):
                # 使用更新后的格式要求重新生成
                st.session_state["doc_bytes"] = None
                st.session_state["doc_preview_mode"] = False
                st.rerun()
        with col3:
            if st.button("❌ Cancel", use_container_width=True, key="cancel_preview"):
                st.session_state["doc_bytes"] = None
                st.session_state["doc_preview_mode"] = False
                st.session_state["format_adjustment_history"] = []
                st.rerun()


if __name__ == "__main__":
    main()

