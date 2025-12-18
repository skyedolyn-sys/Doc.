"""Markdown 解析和格式配置模块。

当前包含两部分：
1. 默认格式配置（字号、字体、行距等），用于 Word 导出时作为基础样式。
2. 简单的 Markdown 解析，将文本拆分为 title / heading1 / heading2 / body 四类元素。
"""

from __future__ import annotations

from typing import Dict, List, Literal, TypedDict


class ParsedBlock(TypedDict):
    type: Literal["title", "heading1", "heading2", "body"]
    text: str


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
    - 其他非空行 → type: "body"
    - 自动去掉行首的 # 及其后面的空格，只保留纯文本
    """
    blocks: List[ParsedBlock] = []
    has_title = False

    for raw_line in content.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            # 忽略纯空行，不生成 body
            continue

        stripped = line.lstrip()
        
        # 判断标题层级
        if stripped.startswith("###"):
            # 三级标题（二级标题）
            text = _strip_heading_marks(line)
            block_type: ParsedBlock["type"] = "heading2"
        elif stripped.startswith("##"):
            # 二级标题（一级标题）
            text = _strip_heading_marks(line)
            block_type = "heading1"
        elif stripped.startswith("#"):
            # 一级标题（主标题）
            text = _strip_heading_marks(line)
            if not has_title:
                block_type = "title"
                has_title = True
            else:
                # 如果已经有title了，后续的 # 也作为 heading1 处理
                block_type = "heading1"
        else:
            # 正文
            text = stripped
            block_type = "body"

        if text:  # 避免空文本块
            blocks.append(ParsedBlock(type=block_type, text=text))

    return blocks

