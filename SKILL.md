---
name: weekly-exam
description: 自动完成周周考在线考试（问卷星），输入姓名、手机号和等待时间即可自动答题并提交。
user-invocable: true
metadata:
  openclaw:
    requires:
      bins: ["python3", "pip"]
---

# 周周考自动答题 Skill

## 触发条件

当用户提到以下关键词时使用此 Skill：
- "周周考"、"帮我考试"、"自动答题"、"帮我周周考"

## 需要的参数

使用此 Skill 前，必须向用户收集以下信息：

| 参数 | 是否必填 | 默认值 | 说明 |
|------|---------|--------|------|
| 姓名 | ✅ 必填 | - | 考试用的真实姓名 |
| 手机号 | ✅ 必填 | - | 考试用的手机号 |
| 地市 | 可选 | 南宁 | 可选：南宁/柳州/桂林/梧州/北海/防城港/钦州/贵港/玉林/百色/贺州/河池/来宾/崇左 |
| 模拟环境 | 可选 | wecom_android | 可选：wecom_iphone/wecom_android/wechat_iphone/wechat_android/pc |
| 等待时间(秒) | 可选 | 600 | 答完题后等待多少秒再提交（建议600秒以上防作弊检测） |

## 工作流

### 第一步：安装依赖

检查并安装所需 Python 包和 Chromium 浏览器内核：

```bash
pip install playwright openpyxl
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright playwright install chromium
```

如果 `playwright install chromium` 失败，尝试：
```bash
python3 -m playwright install chromium
```

### 第二步：定位脚本和题库

此 Skill 目录下包含：
- `exam_auto.py` — 自动答题 CLI 脚本
- `question_bank.xlsx` — 题库 Excel 文件

### 第三步：运行脚本

使用收集到的参数执行脚本：

```bash
cd <此skill所在目录>
python3 exam_auto.py --name "用户姓名" --phone "用户手机号" --city "地市" --env "模拟环境" --wait 等待秒数 --output-dir ./exam_output
```

**参数示例：**
```bash
python3 exam_auto.py --name "张三" --phone "13800138000" --city "南宁" --env "wecom_android" --wait 600 --output-dir ./exam_output
```

### 第四步：返回结果

脚本会输出以下信息：
- 题库加载统计
- 每道题的匹配情况
- 等待倒计时
- 最终提交的成绩

将最终成绩反馈给用户。

### 第五步：展示截图

脚本会在 `--output-dir` 指定的目录下生成两张截图：
- `exam_preview.png` — 答题完成后的预览截图（显示所有已选答案）
- `exam_score.png` — 提交后的最终成绩截图

将这两张截图展示给用户查看。

## 错误处理

- 如果依赖安装失败，提示用户检查网络连接或手动安装
- 如果浏览器启动失败，提示可能需要安装系统依赖：`playwright install-deps chromium`
- 如果部分题目未匹配到答案，告知用户未匹配的题目数量

## 注意事项

- 等待时间建议设置为 600 秒（10 分钟）以上，过短可能触发反作弊
- 题库文件 `question_bank.xlsx` 可自行替换更新
- 此 Skill 需要网络连接来访问考试页面
