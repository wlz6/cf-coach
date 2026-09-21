import time
from typing import List, Optional, Tuple
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.cf_client import CFProblem
from src.agent.prompts import (
    COACH_SYSTEM_PROMPT,
    EVALUATE_IDEA_PROMPT,
    GENERATE_CODE_PROMPT,
    SIMPLIFY_PROBLEM_PROMPT
)
from src.logger import logger


class CoachChain:
    def __init__(self, llm: ChatOpenAI):
        self.llm = llm
        self.current_problem: Optional[CFProblem] = None
        self.current_summary: str = ""
        self.chat_history: List[BaseMessage] = []

    def set_problem(self, problem: CFProblem, summary: str = ""):
        """设置当前题目并重置对话轮次。"""
        self.current_problem = problem
        self.current_summary = summary
        self.chat_history = [
            SystemMessage(content=COACH_SYSTEM_PROMPT)
        ]
        logger.debug("CoachChain 重置题目: CF{}{}, 初始模型长度: {}", problem.contest_id, problem.index, len(summary))

    def simplify_problem(self, problem: CFProblem) -> str:
        """剥离背景故事，提取纯粹的算法数学模型与时空限制。"""
        t0 = time.time()
        logger.info("开始调用 LLM 提炼题面模型: CF{}{}", problem.contest_id, problem.index)
        samples_str = ""
        for idx, (inp, outp) in enumerate(problem.samples, 1):
            samples_str += f"Sample #{idx}:\n[Input]\n{inp}\n[Output]\n{outp}\n\n"

        prompt_text = SIMPLIFY_PROBLEM_PROMPT.format(
            contest_id=problem.contest_id,
            index=problem.index,
            name=problem.name,
            time_limit=problem.time_limit,
            memory_limit=problem.memory_limit,
            statement=problem.statement_text[:3500],  # 控制上下文长度
            input_spec=problem.input_spec[:1500],
            output_spec=problem.output_spec[:1000],
            samples=samples_str.strip() or "无样例",
            note=problem.note[:1000] or "无"
        )

        messages = [
            SystemMessage(content=COACH_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text)
        ]

        response = self.llm.invoke(messages)
        summary = response.content
        self.set_problem(problem, summary)
        logger.info("题面模型提炼完成 (耗时: {:.2f}s, 生成字符数: {})", time.time() - t0, len(summary))
        return summary

    def evaluate_idea(self, user_idea: str) -> Tuple[bool, str]:
        """评估用户输入的算法思路。

        返回 (is_passed, reply_text)
        """
        if not self.current_problem:
            logger.warning("evaluate_idea 失败: 当前未加载任何题目")
            return False, "当前未加载题目。"

        logger.info("开始评估用户思路 (题号: CF{}{}, 思路长度: {})", self.current_problem.contest_id, self.current_problem.index, len(user_idea))
        logger.debug("用户思路详情: {}", user_idea)
        t0 = time.time()

        eval_prompt = EVALUATE_IDEA_PROMPT.format(
            contest_id=self.current_problem.contest_id,
            index=self.current_problem.index,
            name=self.current_problem.name,
            time_limit=self.current_problem.time_limit,
            memory_limit=self.current_problem.memory_limit,
            summary=self.current_summary,
            user_idea=user_idea
        )

        self.chat_history.append(HumanMessage(content=eval_prompt))
        response = self.llm.invoke(self.chat_history)
        reply = response.content
        self.chat_history.append(AIMessage(content=reply))

        is_passed = "[VERDICT: PASS]" in reply
        clean_reply = reply.replace("[VERDICT: PASS]", "").strip()

        logger.info("思路评估完毕 (耗时: {:.2f}s, 判定结果: {})", time.time() - t0, "PASS" if is_passed else "REJECT/HINT")
        return is_passed, clean_reply

    def request_hint(self) -> str:
        """用户主动请求一级启发式提示。"""
        if not self.current_problem:
            return "当前未加载题目。"

        logger.info("用户请求 Hint 点拨 (CF{}{})", self.current_problem.contest_id, self.current_problem.index)
        t0 = time.time()
        hint_prompt = (
            "选手目前没有完整思路，请求你的启发性点拨。"
            "请严格遵循规则：只给出【1 个最基础的思考切入点】或【数据范围暗含的时间复杂度量级】，"
            "严禁直接说明具体算法或题解，仅输出 1-2 句话作为启发。"
        )
        self.chat_history.append(HumanMessage(content=hint_prompt))
        response = self.llm.invoke(self.chat_history)
        reply = response.content
        self.chat_history.append(AIMessage(content=reply))
        logger.info("Hint 点拨生成完成 (耗时: {:.2f}s)", time.time() - t0)
        return reply

    def generate_code(self) -> str:
        """生成现代 C++ 的 AC 级别代码及简要注释。"""
        if not self.current_problem:
            return "当前未加载题目。"

        logger.info("开始请求生成 C++ AC 代码 (CF{}{})", self.current_problem.contest_id, self.current_problem.index)
        t0 = time.time()
        code_prompt = GENERATE_CODE_PROMPT.format(
            contest_id=self.current_problem.contest_id,
            index=self.current_problem.index,
            name=self.current_problem.name,
            summary=self.current_summary
        )

        messages = [
            SystemMessage(content="你是一名顶级算法竞赛金牌选手与现代 C++ 专家。用户已显式请求 /code 参考代码，请直接提供一份完整、可直接在 Codeforces 提交并 AC 的现代 C++ 标准代码，并附带简要关键注释与复杂度说明。"),
            HumanMessage(content=code_prompt)
        ]
        response = self.llm.invoke(messages)
        content = response.content
        logger.info("C++ 代码生成完毕 (耗时: {:.2f}s, 代码字符数: {})", time.time() - t0, len(content))
        return content.replace("[VERDICT: PASS]", "").strip()

