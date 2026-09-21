import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.logger import logger


class Storage:
    def __init__(self, db_path: str = "data/cf_coach.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.debug("Storage 初始化完成，数据库路径: {}", self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS problems (
                    id TEXT PRIMARY KEY,               -- e.g. "1800A"
                    contest_id INTEGER NOT NULL,
                    problem_index TEXT NOT NULL,
                    name TEXT NOT NULL,
                    rating INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '',
                    status TEXT NOT NULL,              -- 'SOLVED', 'ATTEMPTED', 'SKIPPED'
                    attempts_count INTEGER DEFAULT 1,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    solved_at TIMESTAMP,
                    user_notes TEXT DEFAULT ''
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cached_problems (
                    id TEXT PRIMARY KEY,
                    contest_id INTEGER NOT NULL,
                    problem_index TEXT NOT NULL,
                    name TEXT NOT NULL,
                    rating INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '',
                    time_limit TEXT DEFAULT '2.0s',
                    memory_limit TEXT DEFAULT '256MB',
                    statement_text TEXT DEFAULT '',
                    input_spec TEXT DEFAULT '',
                    output_spec TEXT DEFAULT '',
                    samples_json TEXT DEFAULT '[]',
                    note TEXT DEFAULT '',
                    summary TEXT DEFAULT '',           -- 已提炼的纯粹数学模型
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    problem_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    @staticmethod
    def make_problem_id(contest_id: int, index: str) -> str:
        return f"{contest_id}{index.upper()}"

    def get_solved_problem_ids(self) -> Set[str]:
        """获取所有本地记录为已解决的题目 ID 集合。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM problems WHERE status = 'SOLVED'")
            rows = cursor.fetchall()
            return {row["id"] for row in rows}

    def is_solved(self, contest_id: int, index: str) -> bool:
        pid = self.make_problem_id(contest_id, index)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM problems WHERE id = ? AND status = 'SOLVED'", (pid,))
            return cursor.fetchone() is not None

    def record_attempt(self, contest_id: int, index: str, name: str, rating: int = 0, tags: str = ""):
        pid = self.make_problem_id(contest_id, index)
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO problems (id, contest_id, problem_index, name, rating, tags, status, attempts_count, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, 'ATTEMPTED', 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    attempts_count = attempts_count + 1
                """,
                (pid, contest_id, index.upper(), name, rating, tags, now)
            )
            conn.commit()

    def mark_solved(self, contest_id: int, index: str, name: str, rating: int = 0, tags: str = "", notes: str = ""):
        pid = self.make_problem_id(contest_id, index)
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO problems (id, contest_id, problem_index, name, rating, tags, status, solved_at, user_notes)
                VALUES (?, ?, ?, ?, ?, ?, 'SOLVED', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = 'SOLVED',
                    solved_at = ?,
                    user_notes = CASE WHEN ? != '' THEN ? ELSE user_notes END
                """,
                (pid, contest_id, index.upper(), name, rating, tags, now, notes, now, notes, notes)
            )
            conn.commit()
            logger.info("CF{}{} 已成功标记为已解决 (SOLVED)", contest_id, index)

    def save_chat_message(self, contest_id: int, index: str, role: str, content: str):
        pid = self.make_problem_id(contest_id, index)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chat_history (problem_id, role, content) VALUES (?, ?, ?)",
                (pid, role, content)
            )
            conn.commit()

    def get_stats(self) -> Dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM problems WHERE status = 'SOLVED'")
            solved_cnt = cursor.fetchone()["cnt"]
            cursor.execute("SELECT COUNT(*) as cnt FROM problems WHERE status = 'ATTEMPTED'")
            attempted_cnt = cursor.fetchone()["cnt"]
            return {"solved": solved_cnt, "attempted": attempted_cnt}

    def save_cached_problem(
        self,
        contest_id: int,
        index: str,
        name: str,
        rating: int = 0,
        tags: str = "",
        time_limit: str = "2.0s",
        memory_limit: str = "256MB",
        statement_text: str = "",
        input_spec: str = "",
        output_spec: str = "",
        samples_json: str = "[]",
        note: str = "",
        summary: str = ""
    ):
        """缓存抓取到的题目详情与提炼出的模型。"""
        pid = self.make_problem_id(contest_id, index)
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO cached_problems (
                    id, contest_id, problem_index, name, rating, tags,
                    time_limit, memory_limit, statement_text, input_spec, output_spec,
                    samples_json, note, summary, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    rating = excluded.rating,
                    tags = excluded.tags,
                    time_limit = excluded.time_limit,
                    memory_limit = excluded.memory_limit,
                    statement_text = excluded.statement_text,
                    input_spec = excluded.input_spec,
                    output_spec = excluded.output_spec,
                    samples_json = excluded.samples_json,
                    note = excluded.note,
                    summary = CASE WHEN excluded.summary != '' THEN excluded.summary ELSE summary END,
                    updated_at = excluded.updated_at
                """,
                (
                    pid, contest_id, index.upper(), name, rating, tags,
                    time_limit, memory_limit, statement_text, input_spec, output_spec,
                    samples_json, note, summary, now
                )
            )
            conn.commit()

    def update_cached_summary(self, contest_id: int, index: str, summary: str):
        """单独更新题目的纯粹数学模型摘要缓存。"""
        pid = self.make_problem_id(contest_id, index)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE cached_problems SET summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (summary, pid)
            )
            conn.commit()

    def get_cached_problem(self, contest_id: int, index: str) -> Optional[dict]:
        """获取本地缓存的题目详情。若未缓存则返回 None。"""
        pid = self.make_problem_id(contest_id, index)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cached_problems WHERE id = ?", (pid,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def set_active_problem(self, contest_id: int, index: str):
        """设置当前正在思考训练且尚未解决的题目。"""
        pid = self.make_problem_id(contest_id, index)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO app_state (key, value) VALUES ('active_problem', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (pid,)
            )
            conn.commit()
            logger.debug("当前进行中未完成题目已锁定: CF{}{}", contest_id, index)

    def get_active_problem(self) -> Optional[Tuple[int, str]]:
        """获取当前尚未解决的活跃题目 (contest_id, index)。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_state WHERE key = 'active_problem'")
            row = cursor.fetchone()
            if not row or not row["value"]:
                return None

            pid = row["value"]
            # 校验该题目是否已经在 problems 表中被标记为 SOLVED
            cursor.execute("SELECT status FROM problems WHERE id = ?", (pid,))
            prob_row = cursor.fetchone()
            if prob_row and prob_row["status"] == "SOLVED":
                # 如果已经解决，自动清除活跃标记
                cursor.execute("DELETE FROM app_state WHERE key = 'active_problem'")
                conn.commit()
                logger.debug("题目 {} 已处于 SOLVED 状态，自动清理 active 状态", pid)
                return None

            # 解析 contest_id 和 index
            cid_str = ""
            idx_str = ""
            for i, ch in enumerate(pid):
                if ch.isalpha():
                    cid_str = pid[:i]
                    idx_str = pid[i:].upper()
                    break
            if cid_str and idx_str:
                return int(cid_str), idx_str
        return None

    def clear_active_problem(self):
        """清除当前活跃题目状态（题目已通过、已pass或用户换题）。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM app_state WHERE key = 'active_problem'")
            conn.commit()
            logger.debug("当前活跃未完成题目状态已清除")

