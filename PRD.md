# Doc. — AI-Powered Document Formatter

## 项目概述
一个 Web 应用，解决 AI 生成内容的"最后一公里"问题：格式合规。

用户输入：
1. 格式要求（从 syllabus 复制的自然语言描述）
2. Markdown 格式的内容

输出：符合格式要求的 `.docx` 文件，可直接提交。

## 技术栈
- **前端+后端**: Streamlit (Python)
- **文档生成**: python-docx
- **LLM**: Gemini API / 智谱 API
- **部署**: Streamlit Cloud

## MVP 功能范围

### 支持的功能
| 功能 | 说明 |
|------|------|
| 格式要求输入 | 文本框，粘贴 syllabus 格式说明 |
| 内容输入 | 文本框，支持 Markdown 格式 |
| LLM 解析 | 将自然语言格式要求转为结构化配置 |
| 文档生成 | 生成符合格式的 .docx 文件 |
| 下载 | 一键下载生成的文档 |
| 格式模板 | 保存/加载常用格式配置 |
| 中英文支持 | 支持仿宋、宋体、Times New Roman 等常用字体 |

### 支持的格式属性
- 页面：纸张大小（A4）、页边距
- 字体：中文字体、英文字体、字号
- 样式：加粗、对齐方式（居中/左对齐）
- 间距：行距、段前段后间距
- 结构：标题、一级标题、正文

### 暂不支持
- 表格、图片
- 脚注/尾注
- 自动生成目录
- 直接输出 PDF

### 新增需求（待迭代）
- **文件直接上传**：支持 PDF / CSV / Markdown 上传，通过 AI 识别其中的格式要求与文档内容，减少手工粘贴。
- **正文格式细化**：中文正文段落需自动首行缩进 2 个中文字符；Markdown 中的 `*` 等标记字符需要在输出中剔除，避免遗留原始标记。

---

```markdown
# Doc. — AI-Powered Document Formatter

## 项目概述

一个 Web 应用，解决 AI 生成内容的"最后一公里"问题：格式合规。

用户输入：
1. 格式要求（从 syllabus 复制的自然语言描述）
2. Markdown 格式的内容

输出：符合格式要求的 `.docx` 文件，可直接提交。

## 技术栈

- **前端+后端**: Streamlit (Python)
- **文档生成**: python-docx
- **LLM**: Gemini API / 智谱 API
- **部署**: Streamlit Cloud

## MVP 功能范围

### 支持的功能

| 功能 | 说明 |
|------|------|
| 格式要求输入 | 文本框，粘贴 syllabus 格式说明 |
| 内容输入 | 文本框，支持 Markdown 格式 |
| LLM 解析 | 将自然语言格式要求转为结构化配置 |
| 文档生成 | 生成符合格式的 .docx 文件 |
| 下载 | 一键下载生成的文档 |
| 格式模板 | 保存/加载常用格式配置 |
| 中英文支持 | 支持宋体、Times New Roman 等字体 |

### 支持的格式属性

- 页面：纸张大小（A4）、页边距
- 字体：中文字体、英文字体、字号
- 样式：加粗、对齐方式（居中/左对齐）
- 间距：行距、段前段后间距
- 结构：标题、一级标题、正文

### 暂不支持

- 表格、图片
- 脚注/尾注
- 自动生成目录
- 直接输出 PDF


## 开发阶段

### Phase 1：硬编码原型（先跑通流程）

**目标**：不接 LLM，用硬编码的格式配置，验证"Markdown 输入 → Word 输出"流程。

**产出文件**：
- [app.py](http://app.py) — 主界面
- format_[parser.py](http://parser.py) — 格式解析
- doc_[generator.py](http://generator.py) — 文档生成

### Phase 2：接入 LLM

**目标**：用 LLM 解析自然语言格式要求。

### Phase 3：模板系统

**目标**：允许用户保存和复用格式模板。

### Phase 4：打磨部署

**目标**：完善体验，部署上线。

### Phase X：体验增强（新增）

**目标**：降低输入成本，强化输出格式细节。

- 支持文件上传（PDF / CSV / Markdown），自动识别格式要求与正文内容。
- 正文格式增强：中文正文段首自动缩进 2 个字符；清理 Markdown 段落中的 `*` 等标记符号，确保输出无多余符号。

---

## Phase 1 详细指南

### Step 1.1：创建项目结构

**给 Cursor 的提示词**

```

请在当前项目中创建以下文件：

1. [app.py](http://app.py) — Streamlit 主应用（先写空文件，加个注释说明用途）
2. format_[parser.py](http://parser.py) — Markdown 解析和格式配置
3. doc_[generator.py](http://generator.py) — Word 文档生成
4. requirements.txt — 内容如下：
    
    streamlit
    
    python-docx
    
    python-dotenv
    
5. 创建一个空的 templates 文件夹

创建完成后，告诉我每个文件是干什么的。

```

### Step 1.2：搭建基础界面

**给 Cursor 的提示词：**

```

在 [app.py](http://app.py) 中创建 Streamlit 界面：

1. 页面配置：
    - 标题："Doc. - AI 格式助手"
    - 页面图标：📄
    - 布局：wide
2. 侧边栏（st.sidebar）：
    - 标题："使用说明"
    - 三个步骤说明：
        1. 粘贴格式要求（从 syllabus 复制）
        2. 粘贴 Markdown 内容
        3. 点击生成，下载文档
3. 主区域：
    - 大标题："Doc. - AI 格式助手"
    - 副标题："将 AI 生成的内容转为格式规范的 Word 文档"
    - 文本框1：标签"格式要求"，placeholder"粘贴课程的格式要求..."，高度150
    - 文本框2：标签"内容（Markdown）"，placeholder"粘贴你的内容，用 # 表示标题..."，高度300
    - 按钮："生成文档"

先不写功能逻辑，只搭界面框架。

```

### Step 1.3：实现格式配置 + Markdown 解析

**给 Cursor 的提示词：**

```

在 format_[parser.py](http://parser.py) 中实现：

1. 创建默认格式配置 DEFAULT_CONFIG：

DEFAULT_CONFIG = {

"page": {

"paper_size": "A4",

"margin_cm": 2.5

},

"title": {

"font_cn": "宋体",

"font_en": "Times New Roman",

"size_pt": 16,

"bold": True,

"alignment": "center"

},

"heading1": {

"font_cn": "宋体",

"font_en": "Times New Roman",

"size_pt": 14,

"bold": True,

"alignment": "left"

},

"body": {

"font_cn": "宋体",

"font_en": "Times New Roman",

"size_pt": 12,

"bold": False,

"alignment": "left",

"line_spacing": 1.5

}

}

1. 创建函数 get_default_config()，返回 DEFAULT_CONFIG
2. 创建函数 parse_markdown(content: str) -> list[dict]：
    - 输入 Markdown 文本
    - 输出列表，每项为 {"type": "title"|"heading1"|"body", "text": "..."}
    - 第一个 # 行 → title
    - 后续 # 或 ## 行 → heading1
    - 其他非空行 → body
    - 去掉 # 符号只保留文本

```

### Step 1.4：实现文档生成器

**给 Cursor 的提示词：**

```

在 doc_[generator.py](http://generator.py) 中实现：

1. 创建函数 generate_docx(blocks: list, config: dict) -> Document：
    - 创建新 Word 文档
    - 设置页面为 A4，页边距根据 config["page"]["margin_cm"]
    - 遍历 blocks，为每个 block 添加段落：
        - 根据 block["type"] 从 config 获取格式
        - 设置字体（中文用 font_cn，英文用 font_en）
        - 设置字号、加粗、对齐方式
        - body 类型还要设置行距
    - 返回 Document 对象
2. 创建函数 doc_to_bytes(doc: Document) -> bytes：
    - 将文档保存到 BytesIO
    - 返回字节数据供下载

注意：python-docx 设置中文字体需要处理 [run.font.name](http://run.font.name) 和 run._element.rPr.rFonts

```

### Step 1.5：串联完整流程

**给 Cursor 的提示词：**

```

更新 [app.py](http://app.py)，串联所有模块：

1. 导入：
    
    from format_parser import get_default_config, parse_markdown
    
    from doc_generator import generate_docx, doc_to_bytes
    
2. 点击"生成文档"按钮时：
    
    a. 获取内容输入框的文本
    
    b. 如果内容为空，显示警告 st.warning()
    
    c. 调用 parse_markdown() 解析内容
    
    d. 调用 get_default_config() 获取格式配置
    
    e. 调用 generate_docx() 生成文档
    
    f. 调用 doc_to_bytes() 转为字节
    
    g. 用 [st.download](http://st.download)_button() 显示下载按钮
    
3. 添加 try-except 处理生成错误

用这段内容测试：

# 测试报告

## 第一章 概述

这是正文内容，测试中英文混排 English text here。

## 第二章 分析

更多正文内容。

```

---

## 测试用例

### 中文学术格式测试

**格式要求：**
```

纸张大小A4，页边距2.5厘米

正文宋体小四，标题宋体三号加粗居中

一级标题宋体四号加粗左对齐

1.5倍行距

```

**内容：**
```

# 企业战略分析报告

## 一、公司概述

本报告分析了某科技公司的战略定位。

## 二、市场分析

市场规模持续增长。

```

```
