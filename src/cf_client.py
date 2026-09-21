import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import requests
from bs4 import BeautifulSoup

from src.logger import logger


@dataclass
class CFProblem:
    contest_id: int
    index: str
    name: str
    rating: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    time_limit: str = "2.0s"
    memory_limit: str = "256MB"
    statement_html: str = ""
    statement_text: str = ""
    input_spec: str = ""
    output_spec: str = ""
    samples: List[Tuple[str, str]] = field(default_factory=list)
    note: str = ""

    @property
    def problem_id(self) -> str:
        return f"{self.contest_id}{self.index.upper()}"

    @property
    def url(self) -> str:
        return f"https://codeforces.com/problemset/problem/{self.contest_id}/{self.index}"


class CFClient:
    def __init__(self, cache_dir: Optional[str] = None):
        if not cache_dir:
            from src.config import get_default_data_dir
            self.cache_dir = get_default_data_dir() / "cache"
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        })

    def fetch_user_ac_problems(self, handle: str) -> Set[str]:
        """从 Codeforces 获取用户所有已经 AC 的题目 ID (如 '1800A')。"""
        if not handle:
            return set()
        cache_file = self.cache_dir / f"user_{handle}_ac.json"
        # 缓存 1 小时
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime < 3600):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return set(json.load(f))
            except Exception:
                pass

        url = f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=10000"
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK":
                    ac_ids = set()
                    for sub in data.get("result", []):
                        if sub.get("verdict") == "OK":
                            prob = sub.get("problem", {})
                            cid = prob.get("contestId")
                            idx = prob.get("index")
                            if cid and idx:
                                ac_ids.add(f"{cid}{idx.upper()}")
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(list(ac_ids), f)
                    return ac_ids
        except Exception as e:
            # 网络异常时如果有旧缓存则降级使用
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        return set(json.load(f))
                except Exception:
                    pass
            print(f"[警告] 获取用户 {handle} AC 记录失败: {e}")
        return set()

    def fetch_problemset(self, force_refresh: bool = False) -> List[dict]:
        """获取所有题目列表并缓存。"""
        cache_file = self.cache_dir / "problemset.json"
        # 默认缓存 24 小时
        if not force_refresh and cache_file.exists() and (time.time() - cache_file.stat().st_mtime < 86400):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        url = "https://codeforces.com/api/problemset.problems"
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK":
                    problems = data.get("result", {}).get("problems", [])
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(problems, f)
                    return problems
        except Exception as e:
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            raise RuntimeError(f"获取 Codeforces 题目列表失败: {e}")
        return []

    def get_candidate_problems(
        self,
        handle: str,
        rating_min: int,
        rating_max: int,
        tags: Optional[List[str]] = None,
        solved_in_db: Optional[Set[str]] = None
    ) -> List[dict]:
        """过滤出符合难度、Tag，且用户既未在官方 AC 也未在本地解决的题目列表。"""
        raw_problems = self.fetch_problemset()
        ac_ids = self.fetch_user_ac_problems(handle) if handle else set()
        if solved_in_db:
            ac_ids = ac_ids.union(solved_in_db)

        candidates = []
        tags_set = {t.lower() for t in tags} if tags else set()

        for p in raw_problems:
            cid = p.get("contestId")
            idx = p.get("index")
            if not cid or not idx:
                continue
            pid = f"{cid}{idx.upper()}"
            if pid in ac_ids:
                continue

            rating = p.get("rating")
            if rating is None:
                continue
            if not (rating_min <= rating <= rating_max):
                continue

            if tags_set:
                p_tags = {t.lower() for t in p.get("tags", [])}
                if not tags_set.intersection(p_tags):
                    continue

            candidates.append(p)

        return candidates

    def fetch_problem_detail(self, contest_id: int, index: str, storage: Optional[Any] = None) -> CFProblem:
        """抓取并解析题面详情，支持本地持久化全量缓存。"""
        if storage:
            cached = storage.get_cached_problem(contest_id, index)
            if cached and cached.get("statement_text"):
                logger.info("CF{}{}: 本地 SQLite 缓存命中，跳过网络请求", contest_id, index)
                samples = []
                try:
                    samples = json.loads(cached.get("samples_json", "[]"))
                except Exception:
                    pass
                tags = [t.strip() for t in cached.get("tags", "").split(",") if t.strip()]
                return CFProblem(
                    contest_id=contest_id,
                    index=index,
                    name=cached.get("name", f"{contest_id}{index}"),
                    rating=cached.get("rating"),
                    tags=tags,
                    time_limit=cached.get("time_limit", "2.0s"),
                    memory_limit=cached.get("memory_limit", "256MB"),
                    statement_text=cached.get("statement_text", ""),
                    input_spec=cached.get("input_spec", ""),
                    output_spec=cached.get("output_spec", ""),
                    samples=samples,
                    note=cached.get("note", "")
                )

        logger.info("CF{}{}: 本地无完整缓存，开始发起网络抓取...", contest_id, index)
        t0 = time.time()
        urls = [
            f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
            f"https://codeforces.com/contest/{contest_id}/problem/{index}",
            f"https://mirror.codeforces.com/problemset/problem/{contest_id}/{index}"
        ]

        html_content = ""
        last_err = None
        for url in urls:
            try:
                logger.debug("尝试抓取 URL: {}", url)
                resp = self.session.get(url, timeout=12)
                if resp.status_code == 200 and "problem-statement" in resp.text:
                    html_content = resp.text
                    logger.debug("成功从 {} 获取 HTML 题面", url)
                    break
            except Exception as e:
                last_err = e
                logger.warning("抓取 {} 失败: {}", url, e)
                continue

        if not html_content:
            logger.error("CF{}{} 题面抓取完全失败: {}", contest_id, index, last_err)
            # 降级：如果网络阻断或抓取失败，尝试返回一个基础描述
            return CFProblem(
                contest_id=contest_id,
                index=index,
                name=f"Problem {contest_id}{index}",
                statement_text=f"无法抓取题面 (连接失败: {last_err})，请手动访问: https://codeforces.com/problemset/problem/{contest_id}/{index}"
            )

        soup = BeautifulSoup(html_content, "html.parser")
        ps = soup.find("div", class_="problem-statement")
        if not ps:
            return CFProblem(contest_id=contest_id, index=index, name=f"{contest_id}{index}")

        # 标题
        title_node = ps.find("div", class_="title")
        name = title_node.get_text(strip=True) if title_node else f"{contest_id}{index}"
        # 移除前面的 "A. " 或 "B. "
        name = re.sub(r"^[A-Z0-9]+\.\s*", "", name)

        # 限制
        time_limit_node = ps.find("div", class_="time-limit")
        time_limit = time_limit_node.get_text(strip=True).replace("time limit per test", "").strip() if time_limit_node else "2.0s"
        memory_limit_node = ps.find("div", class_="memory-limit")
        memory_limit = memory_limit_node.get_text(strip=True).replace("memory limit per test", "").strip() if memory_limit_node else "256MB"

        # 题目描述正文：在 header 之后到 input-specification 之前的节点
        header = ps.find("div", class_="header")
        body_texts = []
        if header:
            curr = header.next_sibling
            while curr and getattr(curr, "get", lambda _: None)("class") != ["input-specification"]:
                # 检查是否遇到 sample-tests 或 output-specification
                cls = getattr(curr, "get", lambda _: None)("class") or []
                if any(c in cls for c in ["sample-tests", "output-specification"]):
                    break
                text = curr.get_text(separator="\n", strip=True) if hasattr(curr, "get_text") else str(curr).strip()
                if text:
                    body_texts.append(text)
                curr = curr.next_sibling

        statement_text = "\n\n".join(body_texts) if body_texts else ps.get_text(separator="\n", strip=True)

        # 输入格式
        input_node = ps.find("div", class_="input-specification")
        input_spec = input_node.get_text(separator="\n", strip=True) if input_node else ""
        input_spec = re.sub(r"^Input\s*", "", input_spec, flags=re.I).strip()

        # 输出格式
        output_node = ps.find("div", class_="output-specification")
        output_spec = output_node.get_text(separator="\n", strip=True) if output_node else ""
        output_spec = re.sub(r"^Output\s*", "", output_spec, flags=re.I).strip()

        # 样例测试
        samples = []
        sample_tests = ps.find("div", class_="sample-tests")
        if sample_tests:
            inputs = sample_tests.find_all("div", class_="input")
            outputs = sample_tests.find_all("div", class_="output")
            for inp, outp in zip(inputs, outputs):
                in_pre = inp.find("pre")
                out_pre = outp.find("pre")
                in_txt = in_pre.get_text(separator="\n", strip=True) if in_pre else ""
                out_txt = out_pre.get_text(separator="\n", strip=True) if out_pre else ""
                # 清理 codeforces 样例中多余的 div 结构
                samples.append((in_txt, out_txt))

        # 提示/Note
        note_node = ps.find("div", class_="note")
        note = note_node.get_text(separator="\n", strip=True) if note_node else ""
        note = re.sub(r"^Note\s*", "", note, flags=re.I).strip()

        problem_obj = CFProblem(
            contest_id=contest_id,
            index=index,
            name=name,
            time_limit=time_limit,
            memory_limit=memory_limit,
            statement_html=str(ps),
            statement_text=statement_text,
            input_spec=input_spec,
            output_spec=output_spec,
            samples=samples,
            note=note
        )

        if storage:
            try:
                storage.save_cached_problem(
                    contest_id=contest_id,
                    index=index,
                    name=name,
                    time_limit=time_limit,
                    memory_limit=memory_limit,
                    statement_text=statement_text,
                    input_spec=input_spec,
                    output_spec=output_spec,
                    samples_json=json.dumps(samples),
                    note=note
                )
                logger.info("CF{}{} 题面抓取解析成功并已持久化入库 (耗时: {:.2f}s)", contest_id, index, time.time() - t0)
            except Exception as e:
                logger.warning("CF{}{} 持久化入库异常: {}", contest_id, index, e)

        return problem_obj
