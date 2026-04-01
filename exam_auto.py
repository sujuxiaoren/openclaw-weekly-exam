#!/usr/bin/env python3
"""周周考自动答题 CLI 脚本 - 供 OpenClaw Skill 调用"""

import argparse
import asyncio
import os
import sys
import re
import subprocess
import importlib
import json
from datetime import datetime

# 国内镜像
PLAYWRIGHT_CDN_MIRROR = "https://npmmirror.com/mirrors/playwright"
EXAM_URL = 'https://kaoshi.wjx.top/vm/rimKLVu.aspx'

# 模拟环境配置
ENV_CONFIGS = {
    "wecom_iphone": {
        "name": "iPhone 企业微信",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 wxwork/4.1.10 MicroMessenger/7.0.1 Language/zh_CN",
        "viewport": {"width": 390, "height": 844},
    },
    "wecom_android": {
        "name": "Android 企业微信",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-G998B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 wxwork/4.1.10 MicroMessenger/7.0.1.2080 NetType/WIFI Language/zh_CN ABI/arm64",
        "viewport": {"width": 412, "height": 915},
    },
    "wechat_iphone": {
        "name": "iPhone 微信",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a24) NetType/WIFI Language/zh_CN",
        "viewport": {"width": 390, "height": 844},
    },
    "wechat_android": {
        "name": "Android 微信",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-G998B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.41.2441(0x28002951) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
        "viewport": {"width": 412, "height": 915},
    },
    "pc": {
        "name": "电脑浏览器",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
    },
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize_text(text):
    if not text:
        return ""
    text = str(text).replace("【多选题】", "").replace("【单选题】", "")
    return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text).lower()



def _get_playwright_driver_cmd():
    """获取 Playwright 驱动命令（兼容新旧版本 API）"""
    try:
        from playwright._impl._driver import compute_driver_executable
        result = compute_driver_executable()
        # 新版返回 tuple (executable, env)，旧版返回 str
        if isinstance(result, tuple):
            driver_path = str(result[0])
        else:
            driver_path = str(result)
        if os.path.isfile(driver_path):
            return [driver_path]
    except Exception:
        pass
    # 兜底：使用 python -m playwright
    return [sys.executable, "-m", "playwright"]


def ensure_dependencies():
    """检查并安装依赖"""
    # 检查 openpyxl
    try:
        importlib.import_module('openpyxl')
        log("✅ openpyxl 已安装")
    except ImportError:
        log("📥 正在安装 openpyxl...")
        subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "-q"], check=True)
        log("✅ openpyxl 安装完成")

    # 检查 playwright
    try:
        importlib.import_module('playwright')
        log("✅ playwright 已安装")
    except ImportError:
        log("📥 正在安装 playwright...")
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright", "-q"], check=True)
        log("✅ playwright 安装完成")

    # 检查 chromium 是否已安装（查找实际可执行文件）
    driver_cmd = _get_playwright_driver_cmd()
    env = os.environ.copy()
    env["PLAYWRIGHT_DOWNLOAD_HOST"] = PLAYWRIGHT_CDN_MIRROR

    chromium_found = False
    browsers_path = env.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if browsers_path and os.path.isdir(browsers_path):
        for item in os.listdir(browsers_path):
            item_path = os.path.join(browsers_path, item)
            if not item.startswith("chromium") or not os.path.isdir(item_path):
                continue
            # 查找实际的 chrome 可执行文件
            for root, dirs, files in os.walk(item_path):
                for f in files:
                    if f in ("chrome", "chrome.exe", "chrome-headless-shell", "chrome-headless-shell.exe"):
                        chromium_found = True
                        break
                if chromium_found:
                    break
            if chromium_found:
                break

    if not chromium_found:
        log("📥 正在使用国内镜像下载 Chromium（约 150MB）...")
        log(f"📡 下载源: {PLAYWRIGHT_CDN_MIRROR}")
        # 先尝试安装系统依赖（Linux）
        if sys.platform == "linux":
            subprocess.run(driver_cmd + ["install-deps", "chromium"], env=env)
        result = subprocess.run(
            driver_cmd + ["install", "chromium"],
            env=env, capture_output=True, text=True
        )
        if result.returncode == 0:
            log("✅ Chromium 安装成功")
        else:
            log(f"❌ Chromium 安装失败: {result.stderr}")
            log("请手动执行: playwright install chromium")
            sys.exit(1)
    else:
        log("✅ Chromium 已就绪")


def load_question_bank(excel_path):
    """加载题库"""
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet = wb.active
    question_db = {}
    rows = list(sheet.iter_rows(values_only=True))

    count = 0
    for row in rows[1:]:
        if len(row) > 7 and row[1] and row[7]:
            q_raw = str(row[1])
            a_raw = str(row[7]).strip().upper()
            match = re.search(r'^([A-H]+)', a_raw)
            clean_ans = match.group(1) if match else a_raw
            norm_q = normalize_text(q_raw)

            if len(norm_q) > 3:
                question_db[norm_q] = clean_ans
                question_db[norm_q[:15]] = clean_ans
                question_db[norm_q[-15:]] = clean_ans
                if "pci" in norm_q and "300" in norm_q:
                    question_db["pci300"] = clean_ans
                count += 1

    question_db["切换准备失败的可能原因有"] = "ABCD"
    question_db["以下事件中可用于频间切换的有"] = "ABC"

    log(f"📚 题库加载完毕，共 {count} 条索引")
    return question_db


async def run_exam(name, phone, city, env_key, excel_path, output_dir):
    """执行考试主流程"""
    from playwright.async_api import async_playwright

    question_db = load_question_bank(excel_path)
    env_config = ENV_CONFIGS.get(env_key, ENV_CONFIGS["wecom_android"])

    log(f"🚀 开始考试: {name} | {city} | 模拟: {env_config['name']}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=env_config["viewport"],
            user_agent=env_config["user_agent"]
        )
        page = await context.new_page()

        log(f"🌐 打开考试页面: {EXAM_URL}")
        await page.goto(EXAM_URL, timeout=60000)
        await page.wait_for_load_state('networkidle')

        # 填写信息
        log("📝 填写个人信息...")
        await page.locator('.field:has-text("姓名") input').fill(name)
        await page.locator('.field:has-text("手机") input').fill(phone)

        # 地市
        await page.click('.select2-container')
        await page.wait_for_timeout(500)
        await page.click(f'.select2-results__option:has-text("{city}")')

        # 答题
        log("✍️ 开始答题...")
        questions = await page.locator('.field.ui-field-contain').all()

        total_q = 0
        matched_q = 0
        unmatched_details = []

        for i, q_el in enumerate(questions):
            label_el = q_el.locator('.field-label .topichtml')
            if await label_el.count() == 0:
                label_el = q_el.locator('.field-label')

            raw_text = await label_el.inner_text()
            if "姓名" in raw_text or "手机" in raw_text or "地市" in raw_text:
                continue

            total_q += 1
            clean_q = normalize_text(raw_text)

            ans = question_db.get(clean_q)
            if not ans: ans = question_db.get(clean_q[:15])
            if not ans: ans = question_db.get(clean_q[-15:])
            if not ans and "pci" in clean_q and "300" in clean_q: ans = "902"
            if not ans and "切换准备失败" in raw_text: ans = "ABCD"
            if not ans and "以下事件中" in raw_text and "频间切换" in raw_text: ans = "ABC"

            short_q = raw_text[:15].replace('\n', ' ')

            if ans:
                matched_q += 1
                log(f"Q{total_q}: {short_q}... -> 🟢 [{ans}]")
            else:
                unmatched_details.append(f"Q{total_q}: {raw_text}")
                log(f"Q{total_q}: {short_q}... -> 🔴 未找到答案")

            options = await q_el.locator('div.label').all()
            if not options:
                options = await q_el.locator('.ui-radio, .ui-checkbox').all()

            if ans:
                clicked = False
                if ans in ["正确", "错误", "对", "错", "902"]:
                    target_text = ans.replace("对", "正确").replace("错", "错误")
                    for opt in options:
                        if target_text in await opt.inner_text():
                            await opt.click()
                            clicked = True
                            break
                if not clicked:
                    for char in ans:
                        if 'A' <= char <= 'H':
                            idx = ord(char) - ord('A')
                            if idx < len(options):
                                await options[idx].click()
                                clicked = True
                if not clicked and options:
                    await options[0].click()
            elif options:
                await options[0].click()

        # 报告
        match_rate = (matched_q / total_q * 100) if total_q > 0 else 0
        match_info = f"总题数 {total_q} | 匹配 {matched_q} | 未匹配 {len(unmatched_details)} | 匹配率 {match_rate:.1f}%"
        log(f"📊 答题完成: {match_info}")

        # 答题预览截图
        preview_path = os.path.join(output_dir, "exam_preview.png")
        await page.screenshot(path=preview_path, full_page=True)
        log(f"📸 答题预览截图已保存: {preview_path}")

        # 写入 waiting_submit 状态
        state_file = os.path.join(output_dir, "state.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({
                "status": "waiting_submit",
                "match_rate": match_rate,
                "match_info": match_info,
                "preview_path": preview_path,
                "unmatched": unmatched_details
            }, f, ensure_ascii=False)

        # 挂机等待用户的交卷信号
        submit_signal_path = os.path.join(output_dir, "submit_now.txt")
        if os.path.exists(submit_signal_path):
            os.remove(submit_signal_path)

        log("⏳ 答题完成！已输出状态文件，进入后台挂机等待用户指令...")
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

        # 提交
        await page.click('#ctlNext')
        try:
            await page.wait_for_selector('#divResult, #totalScore', timeout=10000)
        except:
            pass
        await page.wait_for_timeout(2000)

        score_text = "未知"
        score_el = page.locator('#divResult .score')
        if await score_el.count() > 0:
            score_text = await score_el.inner_text()
        else:
            score_el = page.locator('#totalScore')
            if await score_el.count() > 0:
                score_text = await score_el.inner_text()

        # 成绩截图
        score_path = os.path.join(output_dir, "exam_score.png")
        await page.screenshot(path=score_path, full_page=True)
        log(f"📸 最终成绩截图已保存: {score_path}")

        log(f"🎉 提交完成！最终成绩: {score_text}")
        log(f"📁 截图文件:")
        log(f"   - 答题预览: {preview_path}")
        log(f"   - 最终成绩: {score_path}")

        # 写入 done 状态
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({
                "status": "done",
                "score": score_text,
                "score_path": score_path
            }, f, ensure_ascii=False)

        await browser.close()
        return score_text


def main():
    parser = argparse.ArgumentParser(description="周周考自动答题 CLI")
    parser.add_argument("--name", required=True, help="考试姓名")
    parser.add_argument("--phone", required=True, help="手机号")
    parser.add_argument("--city", default="南宁", help="地市（默认南宁）")
    parser.add_argument("--env", default="wecom_android",
                        choices=list(ENV_CONFIGS.keys()),
                        help="模拟环境（默认wecom_android）")
    parser.add_argument("--excel", default=None,
                        help="题库路径（默认使用同目录下 question_bank.xlsx）")
    parser.add_argument("--output-dir", default=".",
                        help="截图保存目录（默认当前目录）")
    args = parser.parse_args()

    # 题库路径
    if args.excel:
        excel_path = args.excel
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(script_dir, "question_bank.xlsx")

    if not os.path.exists(excel_path):
        log(f"❌ 题库文件不存在: {excel_path}")
        sys.exit(1)

    # 确保依赖
    ensure_dependencies()

    # 确保输出目录存在
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    state_file = os.path.join(output_dir, "state.json")
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f, ensure_ascii=False)

    # 运行考试
    try:
        score = asyncio.run(run_exam(
            name=args.name,
            phone=args.phone,
            city=args.city,
            env_key=args.env,
            excel_path=excel_path,
            output_dir=output_dir
        ))
        if score is not None:
            print(f"\n{'='*40}")
            print(f"  考试完成！成绩: {score}")
            print(f"{'='*40}")
    except Exception as e:
        log(f"❌ 执行失败: {e}")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({"status": "error", "message": str(e)}, f, ensure_ascii=False)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
