# API Key 设置指南

## 问题修复

已修复代码中的 API key 安全问题。现在代码会从环境变量 `ZHIPU_API_KEY` 中读取 API key，而不是硬编码在代码中。

## 设置方法（推荐：使用 .env 文件）

### 方法 1: 创建 .env 文件（最简单）

1. **在项目根目录创建 `.env` 文件**：
   ```bash
   cd '/Users/sky/Documents/MBA/Managerial thinking/Doc.'
   touch .env
   ```

2. **编辑 `.env` 文件，添加你的 API key**：
   ```bash
   # 使用文本编辑器打开 .env 文件
   # 添加以下内容（替换为你的实际 API key）：
   ZHIPU_API_KEY=71fe529b67ec4a82a08ff70052b710e6.3FwsCmF5KHOH1wJa
   ```

   或者使用命令行：
   ```bash
   echo "71fe529b67ec4a82a08ff70052b710e6.3FwsCmF5KHOH1wJa" > .env
   ```

3. **验证设置**：
   ```bash
   # 检查 .env 文件内容
   cat .env
   ```

4. **重启 Streamlit 应用**：
   - 如果应用正在运行，按 `Ctrl+C` 停止
   - 重新运行 `streamlit run app.py`

### 方法 2: 在终端中设置环境变量（临时）

如果你不想创建 .env 文件，可以在启动应用前设置环境变量：

```bash
# 在 macOS/Linux 上
export ZHIPU_API_KEY="ff692275b8544af796bb9991b71ef0b0.IpJzQIwWJ7taKFx5"
streamlit run app.py
```

**注意**：这种方法只在当前终端会话中有效，关闭终端后需要重新设置。

### 方法 3: 在 shell 配置文件中永久设置（macOS）

如果你想永久设置环境变量：

1. **编辑 `~/.zshrc` 文件**（如果你使用 zsh，这是 macOS 的默认 shell）：
   ```bash
   nano ~/.zshrc
   # 或
   vim ~/.zshrc
   ```

2. **添加以下行**：
   ```bash
   export ZHIPU_API_KEY="ff692275b8544af796bb9991b71ef0b0.IpJzQIwWJ7taKFx5"
   ```

3. **保存并重新加载配置**：
   ```bash
   source ~/.zshrc
   ```

4. **验证设置**：
   ```bash
   echo $ZHIPU_API_KEY
   ```

## 验证 API Key 是否设置成功

运行以下命令检查环境变量：

```bash
# 检查环境变量
echo $ZHIPU_API_KEY

# 或者在 Python 中检查
python3 -c "import os; print(os.getenv('ZHIPU_API_KEY'))"
```

如果输出显示你的 API key，说明设置成功。

## 安全建议

1. **不要将 `.env` 文件提交到 Git**：
   - `.env` 文件应该已经在 `.gitignore` 中
   - 确保不要意外提交包含 API key 的文件

2. **不要分享你的 API key**：
   - API key 是私密信息，不要分享给他人
   - 如果 API key 泄露，请立即在智谱AI平台重新生成

3. **使用 .env 文件**：
   - 这是最安全和方便的方法
   - 可以轻松管理多个项目的不同 API key

## 故障排查

### 问题：应用无法读取 API key

1. **检查 .env 文件是否存在**：
   ```bash
   ls -la .env
   ```

2. **检查 .env 文件格式**：
   - 确保格式为：`ZHIPU_API_KEY=your_key_here`
   - 不要有引号（除非值中包含空格）
   - 不要有多余的空格

3. **检查 python-dotenv 是否安装**：
   ```bash
   pip list | grep python-dotenv
   ```
   如果没有，安装它：
   ```bash
   pip install python-dotenv
   ```

4. **重启应用**：
   - 修改 .env 文件后，需要重启 Streamlit 应用才能生效

### 问题：API key 无效

- 检查 API key 是否正确复制（没有多余空格）
- 确认 API key 在智谱AI平台上是有效的
- 检查 API key 是否有使用限制或已过期

## 下一步

设置好 API key 后，可以继续测试应用功能。如果遇到问题，请查看终端或浏览器控制台的错误信息。

