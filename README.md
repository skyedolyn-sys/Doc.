# Doc. – AI Format Assistant

一个基于 Streamlit 的小工具：上传课程 syllabus 的格式要求 + Markdown 内容，一键生成符合排版要求的 Word 文档。

## 功能

- 识别 syllabus 中的格式要求（PDF / 图片 / HTML / Markdown）
- 支持英文 / 中文界面
- 按标题层级解析 Markdown（支持 # / ## / ###）
- 生成可直接提交的 .docx 文档

## 本地运行

# 1. 克隆仓库
git clone git@github.com:skyedolyn-sys/Doc..git
cd Doc.

# 2. 安装依赖（建议虚拟环境）
pip install -r requirements.txt

# 3. 配置环境变量（API Key 等）
cp .env.example .env   # 如果你有示例
# 编辑 .env，填入 ZHIPU_API_KEY=...

# 4. 启动应用
streamlit run app.py## 备注

- 适用于 MBA/学术写作场景
- 推荐从 ChatGPT / Claude 等导出 Markdown 后直接粘贴使用
