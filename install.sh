#!/usr/bin/env bash
# 司南 (Sinán) 一键安装脚本
set -euo pipefail

# ANSI 颜色
CYAN='\033[96m'
DIM='\033[2m'
BOLD='\033[1m'
YELLOW='\033[93m'
GREEN='\033[92m'
RESET='\033[0m'

echo ""
echo -e "  ${CYAN}${BOLD}███████╗██╗███╗   ██╗ █████╗ ███╗   ██╗${RESET}"
echo -e "  ${CYAN}${BOLD}██╔════╝██║████╗  ██║██╔══██╗████╗  ██║${RESET}"
echo -e "  ${CYAN}${BOLD}███████╗██║██╔██╗ ██║███████║██╔██╗ ██║${RESET}"
echo -e "  ${CYAN}${BOLD}╚════██║██║██║╚██╗██║██╔══██║██║╚██╗██║${RESET}"
echo -e "  ${CYAN}${BOLD}███████║██║██║ ╚████║██║  ██║██║ ╚████║${RESET}"
echo -e "  ${CYAN}${BOLD}╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝${RESET}"
echo ""
echo -e "  ${DIM}─── ${RESET}司南 · 嵌入式智能体工作台  ${DIM}v0.1.0${RESET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 创建数据目录
mkdir -p ~/.sinan/{memories,sessions,knowledge,skills}

# 创建默认配置
echo ""
echo "[0/5] 创建配置文件..."
if [ ! -f ~/.sinan/settings.json ]; then
    cp "$SCRIPT_DIR/settings.json.template" ~/.sinan/settings.json
    echo "  ✓ 已创建 ~/.sinan/settings.json"
    echo "    请编辑该文件配置你的模型 API Keys"
else
    echo "  ✓ 配置文件已存在 (~/.sinan/settings.json)"
fi

# 安装 Python 依赖
echo ""
echo "[1/5] 安装 Python 依赖..."
pip install -r requirements.txt

echo ""
echo "[2/5] 安装可选依赖（如有需要请手动执行）..."
echo "  pip install jsonschema      # JSON Schema 校验"
echo "  pip install esptool         # ESP32 烧录"

# 初始化记忆文件
echo ""
echo "[3/5] 初始化记忆文件..."
if [ ! -f ~/.sinan/memories/MEMORY.md ]; then
    echo "# 司南项目记忆" > ~/.sinan/memories/MEMORY.md
    echo "已创建 ~/.sinan/memories/MEMORY.md"
fi
if [ ! -f ~/.sinan/memories/USER.md ]; then
    echo "# 用户偏好" > ~/.sinan/memories/USER.md
    echo "已创建 ~/.sinan/memories/USER.md"
fi

# 安装 sinan 命令
echo ""
echo "[4/5] 安装 sinan 命令..."
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/sinan" << 'WRAPPER'
#!/usr/bin/env bash
# 司南 (Sinán) CLI 启动器
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# 如果从项目目录外运行，使用安装时记录的路径
if [ ! -f "$PROJECT_DIR/agent/__init__.py" ]; then
    PROJECT_DIR="__SINAN_PROJECT_DIR__"
fi
cd "$PROJECT_DIR" && python3 -m agent.cli "$@"
WRAPPER
# 替换占位符为实际项目路径
sed -i "s|__SINAN_PROJECT_DIR__|$SCRIPT_DIR|g" "$BIN_DIR/sinan"
chmod +x "$BIN_DIR/sinan"

# 配置提示
echo ""
echo "[5/5] 配置提示..."
echo "  📁 配置文件: ~/.sinan/settings.json"
echo "   编辑配置: nano ~/.sinan/settings.json"
echo ""
echo "  示例配置:"
echo "  {"
echo '    "model": {'
echo '      "provider": "groq",'
echo '      "name": "llama-3.3-70b-versatile",'
echo '      "api_key": "gsk_your_key_here"'
echo "    }"
echo "  }"
echo ""
echo "  支持的服务: groq, deepseek, zhipu, moonshot, siliconflow, openai, claude, ollama"

# 确保 ~/.local/bin 在 PATH 中
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    SHELL_RC="$HOME/.bashrc"
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    fi
    echo "" >> "$SHELL_RC"
    echo '# 司南 (Sinán) 嵌入式智能体' >> "$SHELL_RC"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
    echo "已添加 $BIN_DIR 到 PATH ($SHELL_RC)"
    echo "请运行: source $SHELL_RC"
fi
echo "已安装 sinan 命令到 $BIN_DIR/sinan"

echo ""
echo -e "  ${GREEN}${BOLD}✓ 安装完成${RESET}"
echo ""
echo -e "  ${DIM}运行${RESET} ${YELLOW}sinan${RESET} ${DIM}开始对话${RESET}"
echo -e "  ${DIM}数据目录: ~/.sinan/${RESET}"
echo ""
