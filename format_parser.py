"""Markdown 解析和格式配置模块。

当前包含两部分：
1. 默认格式配置（字号、字体、行距等），用于 Word 导出时作为基础样式。
2. 简单的 Markdown 解析，将文本拆分为 title / heading1 / heading2 / body 四类元素。
"""

from __future__ import annotations

from typing import Dict, List, Literal, TypedDict, Optional


class ParsedBlock(TypedDict, total=False):
    type: Literal["title", "heading1", "heading2", "body", "table"]
    text: str
    # 当 type == "table" 时，包含解析后的表格数据：List[row:[cell:str]]
    table: Optional[List[List[str]]]


DEFAULT_CONFIG: Dict[str, Dict[str, object]] = {
    "page": {
        "paper_size": "A4",
        "margin_top_cm": 2.5,
        "margin_bottom_cm": 2.5,
        "margin_left_cm": 3.0,
        "margin_right_cm": 1.5,
    },
    "title": {
        "font_cn": "黑体",
        "font_en": "Times New Roman",
        "size_pt": 18,  # 小二号/三号黑体
        "bold": True,
        "alignment": "center",
    },
    "heading1": {
        "font_cn": "黑体",
        "font_en": "Times New Roman",
        "size_pt": 15,  # 小三号/四号黑体
        "bold": True,
        "alignment": "left",
    },
    "heading2": {
        "font_cn": "黑体",
        "font_en": "Times New Roman",
        "size_pt": 14,  # 四号黑体
        "bold": True,
        "alignment": "left",
    },
    "body": {
        "font_cn": "宋体",
        "font_en": "Times New Roman",
        "size_pt": 12,  # 小四号宋体
        "bold": False,
        "alignment": "left",
        "line_spacing": 1.25,  # 1.25倍行距
        "first_line_chars": 2,  # 首行缩进2字符
    },
}


def get_default_config() -> Dict[str, Dict[str, object]]:
    """返回默认格式配置的一个浅拷贝，避免被意外修改。"""
    # 如果后续需要深度不可变，可以改成 deep copy 或 dataclass
    return {k: dict(v) for k, v in DEFAULT_CONFIG.items()}


def _strip_heading_marks(line: str) -> str:
    """移除行首的 # 及其后紧跟的空格，仅保留实际文本。"""
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return stripped

    # 去掉所有连续的 # 以及一个可选空格
    i = 0
    while i < len(stripped) and stripped[i] == "#":
        i += 1
    # 跳过紧跟其后的一个空格（如果有）
    if i < len(stripped) and stripped[i] == " ":
        i += 1
    return stripped[i:].strip()


def parse_markdown(content: str) -> List[ParsedBlock]:
    """将 Markdown 文本解析为结构化的块列表。

    规则：
    - 第一个以 # 开头的非空行 → type: "title"
    - 以 ## 开头的非空行 → type: "heading1"
    - 以 ### 开头的非空行 → type: "heading2"
    - 中文编号格式：
      - 以"一、"、"二、"、"第一章"、"1."等开头 → type: "heading1"
      - 以"（一）"、"（二）"、"(一)"、"(二)"、"1.1"等开头 → type: "heading2"
    - 其他非空行 → type: "body"
    - 自动去掉行首的 # 及其后面的空格，只保留纯文本
    - 忽略 Markdown 分割线（---、***、___等），不会出现在输出中
    """
    import re

    lines = content.splitlines()
    blocks: List[ParsedBlock] = []
    has_title = False
    i = 0

    # Detect a leading "header-like" block (类似邮件抬头)，例如：
    # From: xx
    # To: yy
    # Date: ...
    # 如果文档开始的连续非空行中至少有一定比例匹配 "Key: Value" 模式，则把该段作为一个
    # 特殊的 body 块返回，并标记 no_indent=True（其余样式仍同正文）。
    if i < len(lines):
        j = 0
        header_lines: List[str] = []
        while j < len(lines) and lines[j].strip():
            header_lines.append(lines[j].rstrip("\n"))
            j += 1
            # 限制最大检查行数，避免把整个文档误判为抬头
            if j >= 12:
                break

        if header_lines:
            import re as _re
            def _is_header_line(s: str) -> bool:
                s_strip = s.strip()
                # 常见 Key: Value 格式或包含 @ 的邮件地址或以常见头字段开头
                if _re.match(r'^[A-Za-z0-9 \-]+:\s+.+$', s_strip):
                    return True
                if _re.search(r'[@<>]', s_strip):
                    return True
                if _re.match(r'^(Subject|From|To|Date|Cc|Bcc|Reply-To):', s_strip, _re.I):
                    return True
                return False

            matches = sum(1 for ln in header_lines if _is_header_line(ln))
            # 当匹配行数占比 >= 30% 且至少 1 行匹配时，视为 header-like block
            if matches >= 1 and (matches / len(header_lines)) >= 0.3:
                blocks.append(ParsedBlock(type="body", text="\n".join(header_lines), no_indent=True))
                i = j  # 跳过已处理的抬头区域
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.rstrip("\n")
        if not line.strip():
            i += 1
            continue

        stripped = line.lstrip()

        # 检查是否是 Markdown 分割线（三个或更多连续的 -、* 或 _）
        if re.match(r'^[\s]*[-*_]{3,}[\s]*$', stripped):
            i += 1
            continue

        # 尝试检测 Markdown 表格：当前行包含 '|'，且下一行为分隔线（仅由 '|', '-', ':' 和空格组成）
        if "|" in stripped and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            # 去掉竖线与空格后，剩下的应该只包含 '-' 或 ':' 才认为是表格分隔行
            sep_candidate = next_stripped.replace("|", "").replace(" ", "")
            if sep_candidate and all(ch in "-:" for ch in sep_candidate):
                # 解析表格头和后续行，直到遇到空行或不含竖线的行
                table_rows: List[List[str]] = []
                def split_row(r: str) -> List[str]:
                    parts = [c.strip() for c in r.split("|")]
                    # 移除可能的首尾空字符串（来自首尾的 |）
                    if parts and parts[0] == "":
                        parts = parts[1:]
                    if parts and parts[-1] == "":
                        parts = parts[:-1]
                    return parts

                header = split_row(stripped)
                table_rows.append(header)
                i += 2  # 跳过 separator 行

                while i < len(lines):
                    row_line = lines[i].rstrip("\n")
                    if not row_line.strip() or "|" not in row_line:
                        break
                    row_cells = split_row(row_line)
                    table_rows.append(row_cells)
                    i += 1

                blocks.append(ParsedBlock(type="table", text="", table=table_rows))
                continue

        block_type: ParsedBlock["type"] = "body"
        text = stripped

        # 优先检查 Markdown 标题格式
        if stripped.startswith("###"):
            text = _strip_heading_marks(line)
            block_type = "heading2"
        elif stripped.startswith("##"):
            text = _strip_heading_marks(line)
            block_type = "heading1"
        elif stripped.startswith("#"):
            text = _strip_heading_marks(line)
            if not has_title:
                block_type = "title"
                has_title = True
            else:
                block_type = "heading1"
        else:
            # 检查中文编号格式的一级标题
            if re.match(r'^[一二三四五六七八九十]+[、.]', stripped) or \
               re.match(r'^第[一二三四五六七八九十]+[章节部分]', stripped) or \
               re.match(r'^\d+[、.]', stripped):
                if not has_title:
                    block_type = "title"
                    has_title = True
                else:
                    block_type = "heading1"
                text = stripped
            elif re.match(r'^[（(][一二三四五六七八九十]+[）)]', stripped) or \
                 re.match(r'^\d+\.\d+', stripped) or \
                 re.match(r'^\d+[）)]', stripped):
                block_type = "heading2"
                text = stripped
            else:
                text = stripped
                block_type = "body"

        if text:
            blocks.append(ParsedBlock(type=block_type, text=text))
        i += 1

    return blocks

