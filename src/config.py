import os
import yaml
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field


class CodeforcesConfig(BaseModel):
    handle: str = Field(default="", description="Codeforces 用户名/ID")
    rating_min: int = Field(default=1200, description="题目最低难度 Rating")
    rating_max: int = Field(default=2200, description="题目最高难度 Rating")
    tags: List[str] = Field(default_factory=list, description="题目算法标签过滤列表")


class LLMConfig(BaseModel):
    provider: str = Field(default="openai_compatible", description="模型类型 (openai_compatible / ollama / vllm)")
    base_url: str = Field(default="https://api.openai.com/v1", description="LLM 服务 Base URL")
    api_key: str = Field(default="EMPTY", description="API 密钥")
    model: str = Field(default="gpt-4o", description="模型标识或 endpoint")
    temperature: float = Field(default=0.2, description="采样温度")
    max_tokens: int = Field(default=4096, description="单次生成最大 Token 数")


class StorageConfig(BaseModel):
    db_path: str = Field(default="data/cf_coach.db", description="SQLite 数据库路径")


class AppConfig(BaseModel):
    codeforces: CodeforcesConfig = Field(default_factory=CodeforcesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def find_config_file(preferred_path: Optional[str] = None) -> Optional[Path]:
    """按优先级寻找配置文件。"""
    candidates = []
    if preferred_path:
        candidates.append(Path(preferred_path).expanduser())
    
    # 1. 当前工作目录
    candidates.append(Path.cwd() / "config.yaml")
    # 2. 用户全局配置目录
    candidates.append(Path.home() / ".config" / "cf-coach" / "config.yaml")
    # 3. 代码仓库所在项目目录
    project_root = Path(__file__).resolve().parent.parent
    candidates.append(project_root / "config.yaml")

    for p in candidates:
        if p.is_file():
            return p
    return None


def get_default_data_dir() -> Path:
    """获取数据与缓存存放目录。"""
    data_dir = Path.home() / ".local" / "share" / "cf-coach"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """加载配置并返回 AppConfig 对象。"""
    target_file = find_config_file(config_path)
    data = {}
    if target_file and target_file.is_file():
        with open(target_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    # 若未明确指定绝对路径，数据库路径默认落入用户 share 目录
    storage_cfg = data.get("storage", {})
    raw_db_path = storage_cfg.get("db_path")
    if not raw_db_path or not Path(raw_db_path).is_absolute():
        data.setdefault("storage", {})["db_path"] = str(get_default_data_dir() / "cf_coach.db")

    # 支持环境变量覆盖
    if "CF_HANDLE" in os.environ:
        data.setdefault("codeforces", {})["handle"] = os.environ["CF_HANDLE"]
    if "OPENAI_API_BASE" in os.environ:
        data.setdefault("llm", {})["base_url"] = os.environ["OPENAI_API_BASE"]
    if "OPENAI_API_KEY" in os.environ:
        data.setdefault("llm", {})["api_key"] = os.environ["OPENAI_API_KEY"]
    if "LLM_MODEL" in os.environ:
        data.setdefault("llm", {})["model"] = os.environ["LLM_MODEL"]

    return AppConfig(**data)

