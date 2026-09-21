import os
import random
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PtStyle
from rich.align import Align
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from src.agent.coach_chain import CoachChain
from src.cf_client import CFClient, CFProblem
from src.config import AppConfig, get_default_data_dir
from src.logger import logger
from src.storage import Storage
from src.tex_renderer import convert_tex_in_markdown


COMMANDS = [
    "/next",
    "/hint",
    "/code",
    "/glow",
    "/raw",
    "/pass",
    "/stats",
    "/config",
    "/help",
    "/quit",
    "/exit"
]


class CoachApp:
    def __init__(self, config: AppConfig, cf_client: CFClient, storage: Storage, coach_chain: CoachChain):
        self.config = config
        self.cf_client = cf_client
        self.storage = storage
        self.coach_chain = coach_chain
        self.console = Console()
        self.candidate_problems: List[dict] = []
        self.current_problem: Optional[CFProblem] = None
        self.current_summary: str = ""
        self.glow_path = shutil.which("glow")
        # 实时同步文件：优先在当前打开的工作区目录下生成 PROBLEM.md，并全局备份
        self.workspace_sync_file = Path.cwd() / "PROBLEM.md"
        self.global_sync_file = get_default_data_dir() / "current.md"
        self.sync_file = self.workspace_sync_file

        # 配置 prompt_toolkit 补全与样式
        self.completer = WordCompleter(COMMANDS, ignore_case=True, match_middle=True)
        self.pt_style = PtStyle.from_dict({
            "prompt": "ansicyan bold",
        })
        self.session = PromptSession(completer=self.completer, style=self.pt_style)

    def init_markdown_session(self):
        """在当前打开的工作区目录下生成/重置 PROBLEM.md，并记录题目元信息与数学模型。"""
        try:
            p = self.current_problem
            if not p:
                return
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tags_str = ", ".join(p.tags) if p.tags else "未指定"
            doc = f"# Codeforces CF{p.contest_id}{p.index} - {p.name}\n\n"
            doc += f"> **Rating**: `{p.rating or 'Unrated'}` | **时限**: `{p.time_limit}` | **空间**: `{p.memory_limit}`  \n"
            doc += f"> **原题链接**: [{p.url}]({p.url})  \n"
            doc += f"> **算法标签**: `{tags_str}`  \n"
            doc += f"> **开始时间**: {now_str}\n\n"
            doc += "---\n\n"
            doc += "## ★ 纯粹算法数学模型 (已剥离故事背景)\n\n"
            doc += f"{self.current_summary}\n\n"
            doc += "---\n\n"
            doc += "## 💬 交互训练记录 (实时会话)\n\n"

            # 写入当前打开目录的 PROBLEM.md
            self.workspace_sync_file.write_text(doc, encoding="utf-8")
            # 写入全局备份 current.md
            self.global_sync_file.parent.mkdir(parents=True, exist_ok=True)
            self.global_sync_file.write_text(doc, encoding="utf-8")
        except Exception as e:
            logger.error("初始化工作区 Markdown 文件失败: {}", e)

    def append_markdown_message(self, title: str, content: str):
        """每次交互消息发生时，实时追加同步到当前工作区目录下的 PROBLEM.md。"""
        try:
            now_str = datetime.now().strftime("%H:%M:%S")
            entry = f"\n### {title} ({now_str})\n\n{content}\n\n---\n"

            # 追加到当前工作区目录
            with open(self.workspace_sync_file, "a", encoding="utf-8") as f:
                f.write(entry)
            # 追加到全局备份
            with open(self.global_sync_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.error("追加工作区 Markdown 交互消息失败: {}", e)

    def sync_markdown_file(self, section_name: str, markdown_content: str):
        """兼容旧接口，自动转为追加或初始化。"""
        self.append_markdown_message(f"【{section_name}】", markdown_content)

    def render_markdown_content(self, text: str, title: str = "", border_style: str = "magenta"):
        """统一渲染 Markdown 内容：跨终端自适应排版 + Unicode TeX 增强。"""
        # 预先将 LaTeX 公式转换为 Unicode 字符，避免终端输出生硬代码
        display_text = convert_tex_in_markdown(text)

        is_dumb = os.environ.get("TERM") == "dumb"
        no_color = bool(os.environ.get("NO_COLOR"))

        if self.glow_path and not is_dumb:
            try:
                if title:
                    self.console.rule(f"[bold {border_style}]{title}[/bold {border_style}]")
                cols = shutil.get_terminal_size(fallback=(80, 24)).columns
                # 动态自适应不同终端窗格（如 tmux 垂直切分屏、手机 SSH 小窗口等）
                glow_width = max(20, cols) if cols < 40 else max(30, cols - 2)
                
                # 支持环境变量指定样式，默认 auto 自适应深色/浅色终端背景
                style_mode = "plain" if no_color else os.environ.get("GLOW_STYLE", "auto")

                res = subprocess.run(
                    [self.glow_path, "-s", style_mode, "-w", str(glow_width), "-"],
                    input=display_text,
                    text=True,
                    capture_output=True
                )
                if res.returncode == 0 and res.stdout.strip():
                    sys.stdout.write(res.stdout)
                    if not res.stdout.endswith("\n"):
                        sys.stdout.write("\n")
                    sys.stdout.flush()
                    return
            except Exception as e:
                logger.warning("Glow 渲染失败，降级为 Rich Panel: {}", e)

        # Fallback 到 Rich Panel 渲染（天然支持 dumb/no_color/无glow环境）
        self.console.print(Panel(
            Markdown(display_text),
            title=f"[bold {border_style}]{title}[/bold {border_style}]",
            border_style=border_style,
            expand=True
        ))

    def print_banner(self):
        welcome_text = """
[bold cyan]╔════════════════════════════════════════════════════════════════════╗[/bold cyan]
[bold cyan]║[/bold cyan]          [bold magenta]Codeforces 思维训练终端 (CF-Coach-CLI)[/bold magenta]                   [bold cyan]║[/bold cyan]
[bold cyan]║[/bold cyan]  [dim]专注算法直觉 · 严谨逻辑验证 · 极简题意提炼 · 拒绝无效代码[/dim]  [bold cyan]║[/bold cyan]
[bold cyan]╚════════════════════════════════════════════════════════════════════╝[/bold cyan]
        """
        self.console.print(Align.center(welcome_text))

        table = Table(title="当前运行环境配置", show_header=True, header_style="bold green")
        table.add_column("配置项", style="cyan", width=18)
        table.add_column("数值 / 说明", style="white")

        cf = self.config.codeforces
        llm = self.config.llm
        table.add_row("CF Handle", cf.handle or "[italic dim]未指定[/italic dim]")
        table.add_row("Rating 范围", f"{cf.rating_min} ~ {cf.rating_max}")
        table.add_row("算法 Tags", ", ".join(cf.tags) if cf.tags else "[italic dim]不限[/italic dim]")
        table.add_row("LLM Provider", llm.provider)
        table.add_row("LLM Model", llm.model)
        table.add_row("Glow 渲染器", f"[bold green]✔ 已启用 ({self.glow_path})[/bold green]" if self.glow_path else "[yellow]未安装 (使用 Rich)[/yellow]")
        table.add_row("工作区 Markdown", f"[bold cyan]./{self.workspace_sync_file.name}[/bold cyan] [dim](实时追加会话记录)[/dim]")

        self.console.print(table)
        self.console.print(
            "[dim]💡 提示: 输入思路直接回车评测；输入 [bold yellow]/glow[/bold yellow] 全屏分页；输入 [bold yellow]/hint[/bold yellow] 阶梯点拨；输入 [bold yellow]/help[/bold yellow] 查看所有指令。[/dim]"
        )
        self.console.print(
            f"[dim]📄 实时文档: 已在当前目录生成 [bold cyan]./{self.workspace_sync_file.name}[/bold cyan] (VS Code 内按 [bold yellow]Ctrl+K V[/bold yellow] 即可开启右侧实时预览，原生渲染 TeX 与代码！)[/dim]\n"
        )

    def load_candidates(self):
        with self.console.status("[bold green]正在从 Codeforces 题库筛选未解题目池...", spinner="dots"):
            solved_ids = self.storage.get_solved_problem_ids()
            cf = self.config.codeforces
            self.candidate_problems = self.cf_client.get_candidate_problems(
                handle=cf.handle,
                rating_min=cf.rating_min,
                rating_max=cf.rating_max,
                tags=cf.tags,
                solved_in_db=solved_ids
            )

        if not self.candidate_problems:
            self.console.print(
                "[bold yellow]警告: 当前条件 (Rating {}-{}, Tags: {}) 下未找到符合要求的未解决题目！[/bold yellow]".format(
                    self.config.codeforces.rating_min,
                    self.config.codeforces.rating_max,
                    self.config.codeforces.tags
                )
            )
        else:
            self.console.print(
                f"[bold green]✔ 成功加载候选题目池，共计 [cyan]{len(self.candidate_problems)}[/cyan] 道题目。[/bold green]\n"
            )

    def pick_next_problem(self, specific_id: Optional[str] = None) -> bool:
        """随机挑选或指定题目，优先从本地缓存秒级加载并恢复。"""
        if specific_id:
            cid_match = ""
            idx_match = ""
            for i, ch in enumerate(specific_id):
                if ch.isalpha():
                    cid_match = specific_id[:i]
                    idx_match = specific_id[i:].upper()
                    break
            if not cid_match or not idx_match:
                self.console.print(f"[bold red]错误: 题目编号格式不合法 ({specific_id})，如 1800A[/bold red]")
                return False
            contest_id = int(cid_match)
            index = idx_match
            name = f"{contest_id}{index}"
            rating = 0
            tags = []
        else:
            if not self.candidate_problems:
                self.load_candidates()
                if not self.candidate_problems:
                    return False

            prob_data = random.choice(self.candidate_problems)
            contest_id = prob_data.get("contestId")
            index = prob_data.get("index")
            name = prob_data.get("name", "")
            rating = prob_data.get("rating", 0)
            tags = prob_data.get("tags", [])

        # 检查是否已在本地全量缓存中
        cached_info = self.storage.get_cached_problem(contest_id, index)
        is_fully_cached = cached_info and cached_info.get("statement_text") and cached_info.get("summary")

        if is_fully_cached:
            status_msg = f"[bold green]正在从本地缓存瞬间载入 CF{contest_id}{index}..."
        else:
            status_msg = f"[bold cyan]正在解析 CF{contest_id}{index} 题面详情并剥离背景故事..."

        with self.console.status(status_msg, spinner="dots"):
            problem = self.cf_client.fetch_problem_detail(contest_id, index, storage=self.storage)
            problem.rating = rating or problem.rating
            problem.tags = tags or problem.tags
            problem.name = name or problem.name

            # 标记当前正在尝试
            self.storage.record_attempt(
                contest_id=contest_id,
                index=index,
                name=problem.name,
                rating=problem.rating or 0,
                tags=",".join(problem.tags)
            )
            # 锁定为当前未完成活跃题目
            self.storage.set_active_problem(contest_id, index)

            # 检查提炼模型的本地缓存
            summary = ""
            if cached_info and cached_info.get("summary"):
                summary = cached_info["summary"]
                self.coach_chain.set_problem(problem, summary)
            else:
                try:
                    summary = self.coach_chain.simplify_problem(problem)
                    self.storage.update_cached_summary(contest_id, index, summary)
                except Exception as e:
                    self.console.print(f"[bold red]模型提炼题意失败: {e}[/bold red]")
                    summary = f"### 【原始题面描述】\n\n{problem.statement_text}\n\n**输入格式**:\n{problem.input_spec}\n\n**输出格式**:\n{problem.output_spec}"
                    self.coach_chain.set_problem(problem, summary)

        self.current_problem = problem
        self.current_summary = summary
        # 初始化工作区下的 PROBLEM.md
        self.init_markdown_session()
        self.render_problem_view()
        return True

    def render_problem_view(self):
        if not self.current_problem:
            return

        p = self.current_problem
        tags_str = ", ".join(p.tags) if p.tags else "未公开"
        header_text = f"[bold yellow]CF{p.contest_id}{p.index}[/bold yellow] - [bold white]{p.name}[/bold white] | Rating: [bold cyan]{p.rating or 'Unrated'}[/bold cyan] | 限时: [green]{p.time_limit}[/green] | 空间: [green]{p.memory_limit}[/green]\n[dim]原题链接: {p.url} | 标签: {tags_str}[/dim]"

        self.console.print()
        self.console.print(Panel(
            header_text,
            title="[bold blue]当前训练题目[/bold blue]",
            border_style="blue",
            expand=True
        ))

        self.render_markdown_content(
            self.current_summary,
            title="★ 纯粹算法数学模型 (已剥离故事背景)",
            border_style="magenta"
        )
        self.console.print(
            f"[dim]📄 实时文档: [bold cyan]./{self.workspace_sync_file.name}[/bold cyan] (可在编辑器按 [bold yellow]Ctrl+K V[/bold yellow] 开启右侧实时预览，原生渲染 TeX 与代码！)[/dim]"
        )
        self.console.print(
            "\n[dim]请在下方输入你的状态定义、贪心结论或复杂度；输入 [bold yellow]/glow[/bold yellow] 交互分页全屏浏览；输入 [bold yellow]/hint[/bold yellow] 阶梯点拨 或 [bold yellow]/code[/bold yellow] 查看代码。[/dim]\n"
        )

    def print_help(self):
        table = Table(title="可用指令帮助", show_header=True, header_style="bold yellow")
        table.add_column("指令", style="cyan", width=12)
        table.add_column("功能说明", style="white")

        table.add_row("/next", "跳过当前题目，随机抽取下一道符合条件的未做题目")
        table.add_row("/glow", "使用 Glow 原生全屏分页查看当前题面、公式与代码 (按 q 退出)")
        table.add_row("/hint", "向教练请求 1 级阶梯式思考提示（不会泄露完整解法）")
        table.add_row("/code", "让教练用现代 C++ 输出该题的标准 AC 代码与关键实现注释")
        table.add_row("/raw", "查看 Codeforces 原始英文题面与样例")
        table.add_row("/pass", "手动标记当前题目已通过，并记录至本地 SQLite 数据库")
        table.add_row("/stats", "查看历史做题统计（已解决 / 正在尝试）")
        table.add_row("/config", "查看当前配置与模型信息")
        table.add_row("/help", "显示本帮助信息")
        table.add_row("/quit", "退出训练程序")

        self.console.print(table)

    def handle_command(self, cmd: str) -> bool:
        """处理斜杠指令。返回 False 表示退出程序。"""
        logger.info("执行斜杠指令: {}", cmd.strip())
        parts = cmd.strip().split()
        op = parts[0].lower()

        if op in ("/quit", "/exit"):
            self.console.print("[bold cyan]正在保存进度，退出训练。保持思维敏锐，下次见！[/bold cyan]")
            return False

        elif op == "/help":
            self.print_help()

        elif op == "/next":
            self.storage.clear_active_problem()
            target_id = parts[1] if len(parts) > 1 else None
            self.pick_next_problem(target_id)

        elif op == "/glow":
            if not self.current_problem:
                self.console.print("[yellow]当前未在解题状态，请先执行 /next 出题。[/yellow]")
                return True
            if not self.glow_path:
                self.console.print("[yellow]系统未检测到 glow，无法调用全屏分页。[/yellow]")
                return True
            self.sync_file.parent.mkdir(parents=True, exist_ok=True)
            style_mode = os.environ.get("GLOW_STYLE", "auto")
            subprocess.run([self.glow_path, "-p", "-s", style_mode, str(self.sync_file)])

        elif op == "/hint":
            if not self.current_problem:
                self.console.print("[yellow]当前未在解题状态，请先执行 /next 出题。[/yellow]")
                return True
            with self.console.status("[bold magenta]教练正在针对性准备阶梯点拨...", spinner="bouncingBar"):
                try:
                    hint = self.coach_chain.request_hint()
                except Exception as e:
                    hint = f"请求点拨失败: {e}"
            self.append_markdown_message("💡 教练阶梯点拨 (Hint)", hint)
            self.render_markdown_content(hint, title="💡 教练点拨 (Hint)", border_style="yellow")
            self.console.print(f"[dim]📝 点拨已实时追加至: [bold cyan]./{self.workspace_sync_file.name}[/bold cyan][/dim]\n")

        elif op == "/code":
            if not self.current_problem:
                self.console.print("[yellow]当前未在解题状态，请先执行 /next 出题。[/yellow]")
                return True
            with self.console.status("[bold green]教练正在编写现代 C++ AC 代码并整理实现要点...", spinner="dots"):
                try:
                    code_reply = self.coach_chain.generate_code()
                except Exception as e:
                    code_reply = f"生成代码失败: {e}"
            self.append_markdown_message("💻 现代 C++ 参考 AC 实现", code_reply)
            self.render_markdown_content(code_reply, title="💻 现代 C++ 参考 AC 实现", border_style="green")
            self.console.print(f"[dim]📝 参考代码已实时追加至: [bold cyan]./{self.workspace_sync_file.name}[/bold cyan][/dim]\n")

        elif op == "/raw":
            if not self.current_problem:
                self.console.print("[yellow]当前未在解题状态。[/yellow]")
                return True
            p = self.current_problem
            content = f"# {p.contest_id}{p.index} - {p.name}\n\n"
            content += f"**Time Limit**: {p.time_limit} | **Memory Limit**: {p.memory_limit}\n\n"
            content += f"### Statement\n{p.statement_text}\n\n"
            content += f"### Input\n{p.input_spec}\n\n"
            content += f"### Output\n{p.output_spec}\n\n"
            for i, (inp, outp) in enumerate(p.samples, 1):
                content += f"#### Sample #{i}\nInput:\n```text\n{inp}\n```\nOutput:\n```text\n{outp}\n```\n\n"
            if p.note:
                content += f"### Note\n{p.note}\n"
            self.append_markdown_message("📜 原始题面内容", content)
            self.render_markdown_content(content, title="原始题面内容", border_style="dim")
            self.console.print(f"[dim]📝 原始题面已实时追加至: [bold cyan]./{self.workspace_sync_file.name}[/bold cyan][/dim]\n")

        elif op == "/pass":
            if not self.current_problem:
                self.console.print("[yellow]当前未在解题状态。[/yellow]")
                return True
            p = self.current_problem
            self.storage.clear_active_problem()
            self.storage.mark_solved(
                contest_id=p.contest_id,
                index=p.index,
                name=p.name,
                rating=p.rating or 0,
                tags=",".join(p.tags),
                notes="Manual /pass"
            )
            self.append_markdown_message("✔ 手动标记通过 (/pass)", f"CF{p.contest_id}{p.index} 已手动标记为通过。")
            self.console.print(f"[bold green]✔ 已成功手动标记 CF{p.contest_id}{p.index} 为已解决（已解除当前锁定）！[/bold green]")

        elif op == "/stats":
            stats = self.storage.get_stats()
            table = Table(title="本地思维训练数据统计", show_header=True)
            table.add_column("指标", style="cyan")
            table.add_column("数量", style="bold green")
            table.add_row("已通过 (Solved)", str(stats.get("solved", 0)))
            table.add_row("尝试过 (Attempted)", str(stats.get("attempted", 0)))
            self.console.print(table)

        elif op == "/config":
            self.print_banner()

        else:
            self.console.print(f"[red]未知指令: {op}，输入 [bold yellow]/help[/bold yellow] 查看支持的命令。[/red]")

        return True

    def handle_user_idea(self, idea_text: str):
        if not self.current_problem:
            self.console.print("[yellow]当前没有正在进行的题目，请使用 /next 挑选题目。[/yellow]")
            return

        with self.console.status("[bold cyan]教练正在推演你的算法模型、检查反例与计算复杂度...", spinner="dots"):
            try:
                is_passed, reply = self.coach_chain.evaluate_idea(idea_text)
            except Exception as e:
                is_passed = False
                reply = f"评测接口异常: {e}"

        p = self.current_problem
        self.storage.save_chat_message(p.contest_id, p.index, "user", idea_text)
        self.storage.save_chat_message(p.contest_id, p.index, "coach", reply)

        # 实时同步至工作区 Markdown 会话
        status_tag = "✔ ACCEPTED (思路验证通过)" if is_passed else "✖ 存在反例或逻辑漏洞"
        self.append_markdown_message("👤 我的解题思路", idea_text)
        self.append_markdown_message(f"🤖 教练评测反馈 ({status_tag})", reply)

        if is_passed:
            self.storage.clear_active_problem()
            self.storage.mark_solved(
                contest_id=p.contest_id,
                index=p.index,
                name=p.name,
                rating=p.rating or 0,
                tags=",".join(p.tags),
                notes=idea_text[:200]
            )
            self.render_markdown_content(
                reply,
                title="✔【恭喜！思路通过验证 (ACCEPTED)】",
                border_style="green"
            )
            self.console.print(
                "[bold green]已记录到本地 AC 题单！[/bold green] 可输入 [bold yellow]/code[/bold yellow] 查看标准实现，或输入 [bold yellow]/next[/bold yellow] 挑战下一题。"
            )
            self.console.print(f"[dim]📝 交互会话已实时追加至: [bold cyan]./{self.workspace_sync_file.name}[/bold cyan][/dim]\n")
        else:
            self.render_markdown_content(
                reply,
                title="✖【需要修正 / 存在致命反例或逻辑漏洞】",
                border_style="red"
            )
            self.console.print(
                "[dim]根据上方教练指出的单个反例或逻辑漏洞调整你的思路，再次输入；若卡住可输入 [bold yellow]/hint[/bold yellow] 获取进一步启发。[/dim]"
            )
            self.console.print(f"[dim]📝 交互会话已实时追加至: [bold cyan]./{self.workspace_sync_file.name}[/bold cyan][/dim]\n")

    def run(self):
        self.print_banner()
        # 优先从本地缓存恢复未解决的活跃题目
        active = self.storage.get_active_problem()
        if active:
            cid, idx = active
            self.console.print(f"[bold cyan]📌 检测到上次未解决题目 CF{cid}{idx}，自动从本地缓存恢复！[/bold cyan]")
            self.pick_next_problem(f"{cid}{idx}")
        else:
            self.pick_next_problem()

        while True:
            try:
                prompt_label = f"CF-Coach (CF{self.current_problem.contest_id}{self.current_problem.index if self.current_problem else 'None'}) > "
                user_input = self.session.prompt(prompt_label).strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    keep_running = self.handle_command(user_input)
                    if not keep_running:
                        break
                else:
                    self.handle_user_idea(user_input)

            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[dim]收到中断信号，退出中...[/dim]")
                break
            except Exception as e:
                self.console.print(f"[bold red]运行时异常: {e}[/bold red]")
