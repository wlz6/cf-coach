#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 确保在任意终端（如 Windows Terminal、SSH、tmux、Linux Console）下标准流均为 UTF-8，彻底杜绝 Unicode 编码崩溃
for _stream in (sys.stdout, sys.stderr, sys.stdin):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from src.config import load_config
from src.cf_client import CFClient
from src.storage import Storage
from src.agent.llm_factory import create_llm
from src.agent.coach_chain import CoachChain
from src.tui.app import CoachApp


def parse_args():
    parser = argparse.ArgumentParser(prog="cf-coach", description="Codeforces 思维训练终端 TUI 工具 (CF-Coach-CLI)")
    parser.add_argument("-c", "--config", default=None, help="配置文件路径 (默认自动查找当前目录/全局配置/项目配置)")
    parser.add_argument("--handle", help="Codeforces 用户名/ID (重载配置文件)")
    parser.add_argument("--min-rating", type=int, help="最低难度 Rating")
    parser.add_argument("--max-rating", type=int, help="最高难度 Rating")
    parser.add_argument("--tags", help="算法标签过滤，多个标签以逗号分隔，如 dp,greedy,graphs")
    parser.add_argument("--model", help="LLM 模型名称或 endpoint")
    parser.add_argument("--problem", help="直接进入指定题目训练 (如 1800A, 1999B)")
    parser.add_argument("--glow", action="store_true", help="使用 Glow 全屏分页查看当前训练题目与点拨 (按 q 退出)")
    parser.add_argument("--watch", action="store_true", help="启动 glow-watch 实时监视当前题目与点拨更新")
    parser.add_argument("--debug", action="store_true", help="开启详细 DEBUG 调试日志追踪模式")
    return parser.parse_args()


def main():
    args = parse_args()
    from src.logger import init_logger, logger
    init_logger(debug=args.debug)
    logger.info("启动 CF-Coach-CLI, 参数: {}", vars(args))

    # 快捷支持 glow 查看
    if args.glow or args.watch:
        from src.config import get_default_data_dir
        sync_file = get_default_data_dir() / "current.md"
        if not sync_file.exists():
            print(f"[提示] 当前题目同步文件暂不存在: {sync_file}，请先运行 cf-coach 加载题目。")
            return
        if args.watch:
            import subprocess
            subprocess.run(["glow-watch", str(sync_file)])
        else:
            import subprocess
            subprocess.run(["glow", "-p", "-s", "dark", str(sync_file)])
        return

    config = load_config(args.config)

    # 命令行参数覆盖
    if args.handle:
        config.codeforces.handle = args.handle
    if args.min_rating is not None:
        config.codeforces.rating_min = args.min_rating
    if args.max_rating is not None:
        config.codeforces.rating_max = args.max_rating
    if args.tags:
        config.codeforces.tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.model:
        config.llm.model = args.model

    cf_client = CFClient()
    storage = Storage(config.storage.db_path)
    llm = create_llm(config.llm)
    coach_chain = CoachChain(llm)

    app = CoachApp(config, cf_client, storage, coach_chain)
    
    if args.problem:
        app.print_banner()
        app.pick_next_problem(args.problem)
        while True:
            try:
                prompt_label = f"CF-Coach (CF{app.current_problem.contest_id}{app.current_problem.index if app.current_problem else 'None'}) > "
                user_input = app.session.prompt(prompt_label).strip()
                if not user_input:
                    continue
                if user_input.startswith("/"):
                    if not app.handle_command(user_input):
                        break
                else:
                    app.handle_user_idea(user_input)
            except (KeyboardInterrupt, EOFError):
                app.console.print("\n[dim]收到中断信号，退出中...[/dim]")
                break
    else:
        app.run()


if __name__ == "__main__":
    main()
