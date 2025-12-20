"""Word 文档生成模块。

基于解析后的块结构（来自 ``format_parser.parse_markdown``）和格式配置，
使用 python-docx 生成符合格式要求的 Word 文档。
"""

from __future__ import annotations

from io import BytesIO
from typing import Dict, Iterable, Literal, TypedDict
import logging

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt
from docx.oxml.ns import qn


# 常量：中文字体集合（用于判断是否为中文文档）
CHINESE_FONT_SET_LOWER = {"宋体", "黑体", "微软雅黑", "仿宋", "楷体"}

logger = logging.getLogger(__name__)


class Block(TypedDict):
    type: Literal["title", "heading1", "heading2", "body"]
    text: str


def clean_text(text: str) -> str:
    """清理正文中不希望保留的标记字符，例如 Markdown 的 `*`。"""
    return text.replace("*", "").strip()


def _get_alignment(value: str) -> int:
    """将简单的对齐字符串映射为 python-docx 的对齐常量。"""
    mapping = {
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    return mapping.get(value.lower(), WD_ALIGN_PARAGRAPH.LEFT)


def _apply_paragraph_style(p, style_cfg: Dict[str, object], block_type: str) -> None:
    """根据配置为段落和 run 应用样式，并对正文段落应用首行缩进。
    
    支持的 block_type: title, heading1, heading2, body
    每种类型都会应用对应的样式配置（字体、字号、加粗、对齐等）。
    """
    # 段落对齐
    alignment = style_cfg.get("alignment", "left")
    p.alignment = _get_alignment(str(alignment))

    # 行距（仅 body 需要，一般通过传入 style_cfg 时已包含）
    line_spacing = style_cfg.get("line_spacing")
    if line_spacing and block_type == "body":
        p.paragraph_format.line_spacing = float(line_spacing)

    # 正文首行缩进（以\"字符数\"估算成厘米）
    # 注意：只有 body 类型需要首行缩进，title/heading1/heading2 不需要
    if block_type == "body":
        # 关键修复：不使用默认值2，应该从配置中获取或根据字体判断
        indent_chars = style_cfg.get("first_line_chars")  # 移除默认值2
        size_pt = style_cfg.get("size_pt")
        
        # 调试：显示实际读取的值（仅第一个body段落）
        if not hasattr(_apply_paragraph_style, "_debug_logged"):
            font_cn_dbg = style_cfg.get("font_cn", "未设置")
            logger.debug(
                "🔍 调试 - body配置: first_line_chars=%s, font_cn=%s, size_pt=%s",
                indent_chars,
                font_cn_dbg,
                size_pt,
            )
            _apply_paragraph_style._debug_logged = True
        
        try:
            indent_chars_f = float(indent_chars) if indent_chars is not None else None
            size_pt_f = float(size_pt) if size_pt is not None else 0.0
            
            # 区分不同情景：
            # - 0：如果明确设置为0且是英文文档，会被统一调整为4.5字符
            # - > 0：应用缩进（中文2字符，英文统一4.5字符）
            # - None：根据字体判断默认值（中文字体→2，英文字体→4.5）
            
            if indent_chars_f == 0:
                # 如果明确设置为0，检查是否是英文文档
                font_cn = str(style_cfg.get("font_cn", "")).lower()
                is_chinese_font = font_cn in {n.lower() for n in CHINESE_FONT_SET_LOWER}
                
                if not is_chinese_font and size_pt_f > 0:
                    # 英文文档：统一使用4.5字符（0.5英寸 = 1.27厘米）
                    indent_cm = 1.27
                    p.paragraph_format.first_line_indent = Cm(indent_cm)
                else:
                    # 中文文档：不缩进
                    p.paragraph_format.first_line_indent = Cm(0)
            elif indent_chars_f is not None and indent_chars_f > 0 and size_pt_f > 0:
                # 应用缩进：中文通常2字符，英文统一4.5字符（0.5英寸）
                # 检测是否为英文文档（通过字体判断）
                font_cn = str(style_cfg.get("font_cn", "")).lower()
                is_chinese_font = font_cn in {n.lower() for n in CHINESE_FONT_SET_LOWER}
                
                # 关键修复：对于英文文档（非中文字体），无论 indent_chars_f 的值是多少，
                # 都应该使用固定的 0.5英寸 = 1.27厘米，而不是通过字符数×字号计算
                # 因为字符宽度在不同字体下不同，不能通过字符数×字号计算
                if not is_chinese_font:
                    # 英文文档：统一使用0.5英寸 = 1.27厘米（固定值）
                    # 不依赖 indent_chars_f 的具体值，因为对于英文文档，0.5英寸是标准缩进
                    indent_cm = 1.27
                else:
                    # 中文文档：使用字符数计算
                    # 1 pt ≈ 0.0352778 cm；缩进 = 字号 * 字符数 * 0.0352778
                    indent_cm = size_pt_f * indent_chars_f * 0.0352778
                
                p.paragraph_format.first_line_indent = Cm(indent_cm)
            elif indent_chars_f is None:
                # 配置缺失：根据字体判断默认值
                font_cn = str(style_cfg.get("font_cn", "")).lower()
                if font_cn in {n.lower() for n in CHINESE_FONT_SET_LOWER} and size_pt_f > 0:
                    # 中文字体：2字符缩进
                    indent_cm = size_pt_f * 2.0 * 0.0352778
                    p.paragraph_format.first_line_indent = Cm(indent_cm)
                elif size_pt_f > 0:
                    # 英文字体：统一使用4.5字符（0.5英寸 = 1.27厘米）
                    indent_cm = 1.27
                    p.paragraph_format.first_line_indent = Cm(indent_cm)
        except (TypeError, ValueError):
            # 如果配置异常，跳过缩进设置
            pass

    # 文字样式（在单一 run 上设置）
    run = p.runs[0] if p.runs else p.add_run()
    size_pt = style_cfg.get("size_pt")
    if size_pt:
        run.font.size = Pt(float(size_pt))

    bold = style_cfg.get("bold")
    if bold is not None:
        run.bold = bool(bold)

    # 字体：中文和英文字体的简单处理
    font_cn = style_cfg.get("font_cn") or "宋体"
    font_en = style_cfg.get("font_en") or "Times New Roman"

    # python-docx 的 font.name 主要对应西文字体
    run.font.name = str(font_en)

    # 通过底层 rFonts 同时指定东亚字体（用于中文）
    r = run._element  # noqa: SLF001  # type: ignore[attr-defined]
    rPr = r.get_or_add_rPr()
    rFonts = rPr.rFonts
    rFonts.set(qn("w:eastAsia"), str(font_cn))
    rFonts.set(qn("w:ascii"), str(font_en))
    rFonts.set(qn("w:hAnsi"), str(font_en))


def _set_page_config(doc: Document, page_cfg: Dict[str, object]) -> None:
    """根据配置设置页面大小和边距。"""
    section = doc.sections[0]

    # A4 纵向
    section.orientation = WD_ORIENT.PORTRAIT
    # A4 尺寸（单位：英寸，python-docx 内部使用 EMU）
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)

    # 支持分别设置上下左右页边距，如果未指定则使用统一值
    if "margin_top_cm" in page_cfg:
        section.top_margin = Cm(float(page_cfg.get("margin_top_cm", 2.5)))
        section.bottom_margin = Cm(float(page_cfg.get("margin_bottom_cm", 2.5)))
        section.left_margin = Cm(float(page_cfg.get("margin_left_cm", 3.0)))
        section.right_margin = Cm(float(page_cfg.get("margin_right_cm", 1.5)))
    else:
        # 兼容旧配置：如果只有 margin_cm，使用统一值
        margin_cm = float(page_cfg.get("margin_cm", 2.5))
        margin = Cm(margin_cm)
        section.top_margin = margin
        section.bottom_margin = margin
        section.left_margin = margin
        section.right_margin = margin


def generate_docx(blocks: Iterable[Block], config: Dict[str, Dict[str, object]]) -> Document:
    """根据解析结果 blocks 和配置 config 生成 Word Document 对象。

    - blocks: 由 ``format_parser.parse_markdown`` 返回的结构。
      支持的 block 类型：title, heading1, heading2, body
    - config: 通常为 ``format_parser.get_default_config()`` 的返回值。
      必须包含 page, title, heading1, heading2, body 的配置。
    """
    doc = Document()

    # 页面设置
    page_cfg = config.get("page", {})
    _set_page_config(doc, page_cfg)

    for block in blocks:
        block_type = block.get("type", "body")
        text = clean_text(block.get("text", "") or "")

        # 跳过空文本块，避免生成多余空段落
        if not text:
            continue

        # 选择对应的样式配置；支持 title, heading1, heading2, body
        # 如果 block_type 不在配置中，默认回退到 body
        style_cfg = config.get(block_type, config.get("body", {}))

        # 添加段落
        p = doc.add_paragraph()
        run = p.add_run(text)

        # 应用样式到段落与 run
        # - title/heading1/heading2: 应用字体、字号、加粗、对齐等样式
        # - body: 除了上述样式外，还会应用首行缩进和行距
        _apply_paragraph_style(p, style_cfg, block_type)

    return doc


def doc_to_bytes(doc: Document) -> bytes:
    """将 python-docx 的 Document 对象转成 bytes，供下载使用。"""
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()

