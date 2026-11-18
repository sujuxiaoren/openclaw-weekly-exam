#!/usr/bin/env python3
"""周周考自动答题 CLI 脚本 - 供 OpenClaw Skill 调用"""

import argparse
import asyncio
import importlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import exam_core  # noqa: E402

# 国内镜像
PLAYWRIGHT_CDN_MIRROR = "https://npmmirror.com/mirrors/playwright"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _get_playwright_driver_cmd():
    """获取 Playwright 驱动命令（统一使用 python -m playwright，避免底层 Node 模块在沙箱中路径异常）"""
    return [sys.executable, "-m", "playwright"]


def ensure_dependencies():
    """检查并安装依赖"""
    try:
        importlib.import_module("openpyxl")
        log("✅ openpyxl 已安装")
    except ImportError:
        log("📥 正在安装 openpyxl...")
        subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "-q"], check=True)
        log("✅ openpyxl 安装完成")

    try:
        importlib.import_module("playwright")
        log("✅ playwright 已安装")
    except ImportError:
        log("📥 正在安装 playwright...")
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright", "-q"], check=True)
        log("✅ playwright 安装完成")

    driver_cmd = _get_playwright_driver_cmd()
    env = os.environ.copy()
    env["PLAYWRIGHT_DOWNLOAD_HOST"] = PLAYWRIGHT_CDN_MIRROR

    chromium_found = False
    browsers_path = env.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if not browsers_path:
        if sys.platform == "win32":
            local_app_data = os.environ.get(
                "LOCALAPPDATA", os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local")
            )
            browsers_path = os.path.join(local_app_data, "ms-playwright")
        elif sys.platform == "darwin":
            browsers_path = os.path.expanduser("~/Library/Caches/ms-playwright")
        else:
            browsers_path = os.path.expanduser("~/.cache/ms-playwright")

    if browsers_path and os.path.isdir(browsers_path):
        for item in os.listdir(browsers_path):
            item_path = os.path.join(browsers_path, item)
            if not item.startswith("chromium") or not os.path.isdir(item_path):
                continue
            for _, _, files in os.walk(item_path):
                if any(f in ("chrome", "chrome.exe", "chrome-headless-shell", "chrome-headless-shell.exe") for f in files):
                    chromium_found = True
                    break
            if chromium_found:
                break

    if not chromium_found:
        log("📥 正在使用国内镜像下载 Chromium（约 150MB）...")
        log(f"📡 下载源: {PLAYWRIGHT_CDN_MIRROR}")
        if sys.platform == "linux":
            subprocess.run(driver_cmd + ["install-deps", "chromium"], env=env)
        result = subprocess.run(driver_cmd + ["install", "chromium"], env=env, capture_output=True, text=True)
        if result.returncode == 0:
            log("✅ Chromium 安装成功")
        else:
            log(f"❌ Chromium 安装失败: {result.stderr}")
            log("请手动执行: playwright install chromium")
            sys.exit(1)
    else:
        log("✅ Chromium 已就绪")


def update_question_bank(excel_path):
    """从 GitHub 同步最新题库，基于文件 SHA 校验，如果有更新则拉取"""
    api_url = "https://api.github.com/repos/sujuxiaoren/openclaw-weekly-exam/contents/question_bank.xlsx"
    raw_url = "https://raw.githubusercontent.com/sujuxiaoren/openclaw-weekly-exam/main/question_bank.xlsx"
    proxy_url = "https://ghproxy.net/" + raw_url
    sha_path = excel_path + ".sha"

    log("🔄 正在检查 GitHub 上的题库是否有更新...")
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            remote_sha = data.get("sha")

        local_sha = None
        if os.path.exists(sha_path):
            with open(sha_path, "r", encoding="utf-8") as f:
                local_sha = f.read().strip()

        if os.path.exists(excel_path) and local_sha == remote_sha:
            log("✅ 本地题库已是最新版本，无需更新。")
            return

        log("📥 发现题库有更新，正在下载最新题库...")
        try:
            req = urllib.request.Request(raw_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as response, open(excel_path, "wb") as out_file:
                out_file.write(response.read())
        except Exception:
            log("⚠️ 原始 GitHub 下载通道较慢，正在切换至加速镜像通道...")
            req = urllib.request.Request(proxy_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as response, open(excel_path, "wb") as out_file:
                out_file.write(response.read())

        with open(sha_path, "w", encoding="utf-8") as f:
            f.write(remote_sha)

        log("✅ 题库已成功同步至最新版本！")
    except Exception as e:
        log(f"⚠️ 题库更新检查失败，将继续使用本地历史题库。（错误信息：{e}）")


async def run_exam(name, phone, city, env_key, excel_path, output_dir):
    """执行考试主流程"""
    from playwright.async_api import async_playwright

    bank = exam_core.load_question_bank(excel_path, log_fn=log)
    if bank["count"] == 0:
        raise ValueError("题库中未加载到任何有效题目，请检查 Excel 内容")

    env_config = exam_core.get_env_config(env_key, default_key="wecom_android")
    log(f"🚀 开始考试: {name} | {city} | 模拟: {env_config['name']}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=env_config["viewport"],
            user_agent=env_config["user_agent"],
        )
        page = await context.new_page()

        log(f"🌐 打开考试页面: {exam_core.EXAM_URL}")
        await page.goto(exam_core.EXAM_URL, timeout=60000)
        await page.wait_for_load_state("networkidle")

        await exam_core.fill_personal_info(page, name, phone, city, log_fn=log)
        summary = await exam_core.solve_exam_questions(page, bank, log_fn=log)

        match_info = (
            f"总题数 {summary['total_q']} | 精确 {summary['exact_count']} | "
            f"近似 {summary['approx_count']} | 未命中 {summary['none_count']} | "
            f"精确匹配率 {summary['match_rate']:.1f}%"
        )

        # 答题预览截图
        preview_path = os.path.join(output_dir, "exam_preview.png")
        await page.screenshot(path=preview_path, full_page=True)
        log(f"📸 答题预览截图已保存: {preview_path}")

        approx_briefs = [
            {
                "q_num": r["q_num"],
                "qtype": r["qtype"],
                "level": r["level"],
                "confidence_pct": round(r["confidence"] * 100, 1),
                "raw_q": r["raw_q"],
                "matched_q": r["matched_q"],
                "filled_ans": r["filled_ans"],
            }
            for r in summary["approx_details"]
        ]

        # 写入 waiting_submit 状态
        state_file = os.path.join(output_dir, "state.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "status": "waiting_submit",
                    "match_rate": summary["match_rate"],
                    "match_info": match_info,
                    "exact_count": summary["exact_count"],
                    "approx_count": summary["approx_count"],
                    "none_count": summary["none_count"],
                    "estimated_score": summary["estimated_score"],
                    "confirmed_score": summary["confirmed_score"],
                    "max_score": summary["max_score"],
                    "score_summary": summary["score_summary_text"],
                    "preview_path": preview_path,
                    "approx_details": approx_briefs,
                    "unmatched": summary["unmatched_details"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        # 挂机等待用户的交卷信号
        submit_signal_path = os.path.join(output_dir, "submit_now.txt")
        if os.path.exists(submit_signal_path):
            os.remove(submit_signal_path)

        log("⏳ 答题完成！已输出预估分与状态文件，进入后台挂机等待用户指令...")
        log(f"💡 请查看截图确认。确认完毕后，请创建文件: {submit_signal_path} 来交卷。")

        elapsed = 0
        while elapsed < 3600:  # 最大挂机 1 小时
            if os.path.exists(submit_signal_path):
                log("🚀 检测到交卷信号，立即开始交卷！")
                os.remove(submit_signal_path)
                break
            await asyncio.sleep(2)
            elapsed += 2

        if elapsed >= 3600:
            log("超时：1小时未收到交卷信号，强制关闭。未交卷。")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump({"status": "timeout_closed"}, f, ensure_ascii=False)
            await browser.close()
            return None

        log("✅ 收到交卷信号，开始提交...")
        score_text = await exam_core.submit_exam_and_extract_score(page, log_fn=log)

        score_path = os.path.join(output_dir, "exam_score.png")
        await page.screenshot(path=score_path, full_page=True)
        log(f"📸 最终成绩截图已保存: {score_path}")

        log(f"🎉 提交完成！页面显示: {score_text}（考前预估: {summary['score_summary_text']}）")
        log("📁 截图文件:")
        log(f"   - 答题预览: {preview_path}")
        log(f"   - 最终成绩: {score_path}")

        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "status": "done",
                    "score": score_text,
                    "estimated_score": summary["estimated_score"],
                    "score_summary": summary["score_summary_text"],
                    "score_path": score_path,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        await browser.close()
        return score_text


def main():
    parser = argparse.ArgumentParser(description="周周考自动答题 CLI")
    parser.add_argument("--name", required=True, help="考试姓名")
    parser.add_argument("--phone", required=True, help="手机号")
    parser.add_argument("--city", default="南宁", help="地市（默认南宁）")
    parser.add_argument(
        "--env",
        default="wecom_android",
        choices=list(exam_core.ENV_CONFIGS.keys()),
        help="模拟环境（默认wecom_android）",
    )
    parser.add_argument("--excel", default=None, help="题库路径（默认使用同目录下 question_bank.xlsx）")
    parser.add_argument("--output-dir", default=".", help="截图保存目录（默认当前目录）")
    args = parser.parse_args()

    if args.excel:
        excel_path = args.excel
    else:
        excel_path = os.path.join(_SCRIPT_DIR, "question_bank.xlsx")

    # 尝试检测并更新题库（若传入自定义本地 --excel 则跳过远程覆盖）
    if not args.excel:
        update_question_bank(excel_path)

    if not os.path.exists(excel_path):
        log(f"❌ 题库文件不存在: {excel_path}")
        sys.exit(1)

    ensure_dependencies()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    state_file = os.path.join(output_dir, "state.json")
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f, ensure_ascii=False)

    try:
        score = asyncio.run(
            run_exam(
                name=args.name,
                phone=args.phone,
                city=args.city,
                env_key=args.env,
                excel_path=excel_path,
                output_dir=output_dir,
            )
        )
        if score is not None:
            print(f"\n{'=' * 40}")
            print(f"  考试完成！页面成绩: {score}")
            print(f"{'=' * 40}")
    except Exception as e:
        log(f"❌ 执行失败: {e}")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({"status": "error", "message": str(e)}, f, ensure_ascii=False)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
