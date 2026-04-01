#!/bin/bash
# 周周考 Skill 环境初始化脚本
# 安装 Skill 时执行此脚本，提前安装所有依赖

echo "📦 开始安装周周考 Skill 依赖..."

# 安装 Python 包
echo "📥 安装 openpyxl..."
pip install openpyxl -q

echo "📥 安装 playwright..."
pip install playwright -q

# 安装 Chromium（使用国内镜像）
echo "📥 使用国内镜像下载 Chromium（约 150MB）..."
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright

# 先安装系统依赖（Linux）
playwright install-deps chromium 2>/dev/null || true

# 安装 Chromium 浏览器
playwright install chromium

if [ $? -eq 0 ]; then
    echo "✅ 所有依赖安装完成！可以开始使用周周考 Skill 了。"
else
    echo "❌ Chromium 安装失败，请检查网络连接后重试。"
    exit 1
fi
