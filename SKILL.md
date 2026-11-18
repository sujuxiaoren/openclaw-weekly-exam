---
name: weekly-exam
description: 自动完成周周考在线考试（问卷星），支持考前分数预估、近似匹配提示、长时后台挂机防作弊，答完题后发截图给用户手动确认交卷。
user-invocable: true
metadata:
  openclaw:
    requires:
      bins: ["python3", "pip", "nohup", "cat", "grep"]
---

# 周周考自动答题 Skill

## 触发条件

当用户提到以下关键词时使用此 Skill：
- "周周考"、"帮我考试"、"自动答题"、"帮我周周考"

## 需要的参数

| 参数 | 是否必填 | 默认值 | 说明 |
|------|---------|--------|------|
| 姓名 | ✅ 必填 | - | 考试用的真实姓名 |
| 手机号 | ✅ 必填 | - | 考试用的手机号 |
| 地市 | 可选 | 南宁 | 可选：南宁/柳州/桂林/梧州/北海/防城港/钦州/贵港/玉林/百色/贺州/河池/来宾/崇左 |
| 模拟环境 | 可选 | wecom_android | wecom_iphone / wecom_android / wechat_iphone / wechat_android / pc |

## 安装初始化（安装 Skill 时立即执行）

当用户首次安装此 Skill 后，**你必须执行以下命令**一次以初始化环境：

```bash
cd <此skill所在目录>
bash setup.sh
```

## 工作流（必读核心逻辑）

因为防作弊要求保持在线，脚本不能阻塞大模型执行（会导致超时断开）。因此脚本以**后台运行**形式工作，你通过轮询状态文件 (`state.json`) 来跟进进度。

---

### 第一步：后台启动考试并等待答题完成

**你必须原样执行以下 bash 脚本**，它会启动后台进程，并阻塞约 15 秒等待答题完成：

```bash
cd <此skill所在目录>
mkdir -p ./exam_output
rm -f ./exam_output/state.json ./exam_output/submit_now.txt

echo "正在启动后台进程..."
# 启动后台进程
nohup python3 exam_auto.py --name "用户姓名" --phone "用户手机号" --city "地市" --env "模拟环境" --output-dir ./exam_output > run.log 2>&1 &

echo "等待脚本答题 (约 10-20 秒)..."
# 轮询状态文件直到答题完成
for i in {1..30}; do
  if grep -q '"waiting_submit"' ./exam_output/state.json 2>/dev/null; then
    break
  fi
  if grep -q '"error"' ./exam_output/state.json 2>/dev/null; then
    break
  fi
  sleep 2
done

cat ./exam_output/state.json
```

**执行并读取 JSON 输出结果：**
- 提取 `score_summary` 与 `estimated_score`（考前预估分数，按单选 3 分、多选 5 分、判断 2 分，满分 100 分估算）。
- 提取 `match_info`（精确命中 / 近似匹配 / 未命中统计）。
- 提取 `approx_details`（所有非 100% 精确匹配的题目明细，含相似度与所选答案）。
- 提取 `preview_path`（通常是 `./exam_output/exam_preview.png`）。

**你必须立即发起回复给用户：**
1. **发送预览截图** `exam_preview.png`。
2. **汇报考前预估分数与匹配情况**：展示 `score_summary` 和 `match_info`。
3. **重点提醒近似/低置信度题目**：若 `approx_details` 不为空，**必须逐条列出**题号、网页题目、匹配到的题库参考题、相似度百分比及拟选答案，提醒用户对照截图核对后再决定是否交卷。
4. 告诉用户："答题已完成并进入后台挂机等候。请确认截图与预估分数，准备好后，随时对我说'交卷'即可。"

之后你可以结束工具调用，等待用户的下一次对话指令。

---

### 第二步：处理用户的交卷请求

当用户回复"交卷"、"提交"等指令时，**你必须原样执行以下 bash 脚本**，向后台发送交卷信号并等待提交结果（约 5-10 秒）：

```bash
cd <此skill所在目录>
# 向后台进程发送交卷信号
touch ./exam_output/submit_now.txt

echo "等待脚本交卷..."
for i in {1..15}; do
  if grep -q '"done"' ./exam_output/state.json 2>/dev/null; then
    break
  fi
  if grep -q '"timeout_closed"' ./exam_output/state.json 2>/dev/null; then
    break
  fi
  sleep 2
done

cat ./exam_output/state.json
```

**执行并读取 JSON 输出结果：**
- 提取 `score_path`、`score`（网页抓取结果，若后台关闭显示则为提示文本）以及 `score_summary`（考前预估分）。

**你必须立即发起回复给用户：**
1. **发送交卷后结果截图** `exam_score.png`。
2. 汇报提交结果（以及页面显示成绩或考前预估分数）。

---

## 异常与超时说明

- 后台进程最多等待 **1小时**。如果用户超过 1 小时未说"交卷"，后台会自动关闭（状态变为 `timeout_closed`），当用户再次要求交卷时，需告知已超时未提交。
- 如果在任一步读取到了 `error` 状态，请向用户汇报 JSON 中的 `message` 字段报错信息。
