"""
LLM 配置
支持分任务路由：chat（拟人回复）/ memory（记忆提取）/ profile（画像更新）

优先级: 环境变量 > .env 文件
"""

import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# OpenAI 兼容接口的预设 Provider
PROVIDER_PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "models": {
            "chat": "deepseek-chat",
            "memory": "deepseek-chat",
            "profile": "deepseek-chat",
        },
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": {
            "chat": "qwen-plus",
            "memory": "qwen-turbo",
            "profile": "qwen-turbo",
        },
        "env_key": "QWEN_API_KEY",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": {
            "chat": "moonshot-v1-8k",
            "memory": "moonshot-v1-8k",
            "profile": "moonshot-v1-8k",
        },
        "env_key": "MOONSHOT_API_KEY",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": {
            "chat": "glm-4-flash",
            "memory": "glm-4-flash",
            "profile": "glm-4-flash",
        },
        "env_key": "GLM_API_KEY",
    },
}


class TaskConfig:
    """单个任务的 LLM 配置"""

    __slots__ = ("task", "provider", "api_key", "base_url", "model", "gateway_token",
                 "max_tokens", "temperature", "timeout")

    def __init__(
        self,
        task: str,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        gateway_token: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: int = 30,
    ):
        self.task = task
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.gateway_token = gateway_token
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key not in ("", "your_api_key_here"))

    def validate(self) -> str | None:
        if not self.is_configured():
            return (
                f"未配置 {self.task} 任务的 API Key。\n"
                f"请在 .env 设置 LLM_{self.task.upper()}_API_KEY 或 "
                f"{PROVIDER_PRESETS.get(self.provider, {}).get('env_key', 'API_KEY')}"
            )
        return None


class LLMConfig:
    """多任务 LLM 配置管理"""

    TASKS = ("chat", "memory", "profile")

    def __init__(self):
        self._load_dotenv()
        self._tasks: dict[str, TaskConfig] = {}
        for task in self.TASKS:
            self._tasks[task] = self._build_task_config(task)

        # 向后兼容旧字段（chat 任务）
        chat = self._tasks["chat"]
        self.api_key = chat.api_key
        self.base_url = chat.base_url
        self.model = chat.model
        self.max_tokens = chat.max_tokens
        self.temperature = chat.temperature
        self.timeout = chat.timeout

    def get(self, task: str = "chat") -> TaskConfig:
        return self._tasks.get(task, self._tasks["chat"])

    def is_configured(self, task: str = "chat") -> bool:
        return self.get(task).is_configured()

    def validate(self, task: str = "chat") -> str | None:
        return self.get(task).validate()

    def _build_task_config(self, task: str) -> TaskConfig:
        prefix = f"LLM_{task.upper()}_"
        provider = os.getenv(f"{prefix}PROVIDER") or os.getenv("LLM_PROVIDER", "deepseek")
        provider = provider.lower().strip()

        if provider not in PROVIDER_PRESETS:
            supported = ", ".join(sorted(PROVIDER_PRESETS))
            raise ValueError(f"不支持的 LLM provider: {provider!r}；可选: {supported}")

        preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["deepseek"])

        api_key = (
            os.getenv(f"{prefix}API_KEY")
            or os.getenv(preset["env_key"])
            or os.getenv("LLM_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY", "")
        )

        base_url = (
            os.getenv(f"{prefix}BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or os.getenv(f"{provider.upper()}_BASE_URL")
            or preset["base_url"]
        )
        model = (
            os.getenv(f"{prefix}MODEL")
            or os.getenv(f"{provider.upper()}_MODEL")
            or preset["models"].get(task, preset["models"]["chat"])
        )

        # chat 任务默认更高温度，memory/profile 更低（结构化输出更稳）
        default_temp = 0.85 if task == "chat" else 0.3
        default_tokens = 512 if task == "chat" else 1024

        return TaskConfig(
            task=task,
            provider=provider,
            api_key=api_key.strip(),
            base_url=base_url.rstrip("/"),
            model=model,
            gateway_token=os.getenv("LLM_GATEWAY_TOKEN", "").strip(),
            max_tokens=self._env_number(
                f"{prefix}MAX_TOKENS", "LLM_MAX_TOKENS", default_tokens,
                int, 1, 8192,
            ),
            temperature=self._env_number(
                f"{prefix}TEMPERATURE", "LLM_TEMPERATURE", default_temp,
                float, 0.0, 2.0,
            ),
            timeout=self._env_number(
                "LLM_TIMEOUT", None, 30, int, 1, 300,
            ),
        )

    @staticmethod
    def _env_number(primary, fallback, default, cast, minimum, maximum):
        raw = os.getenv(primary)
        if raw is None and fallback:
            raw = os.getenv(fallback)
        if raw is None:
            return default
        try:
            value = cast(raw)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{primary} 必须是数字，当前为 {raw!r}") from e
        if not minimum <= value <= maximum:
            raise ValueError(f"{primary} 必须在 {minimum} 到 {maximum} 之间")
        return value

    @staticmethod
    def _load_dotenv():
        env_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env",
        )
        if not os.path.exists(env_file):
            return
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key not in os.environ:
                            os.environ[key] = value
        except IOError:
            pass


llm_config = LLMConfig()
