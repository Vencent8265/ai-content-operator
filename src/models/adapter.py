"""
模型适配层 — ModelRouter + CostTracker
─────────────────────────────────────
设计目的：换模型 = 改配置，不改业务代码

用法：
    router = ModelRouter.from_config("config/models.yaml")
    response = router.call("content_gen", messages=[...])
    # 在配置里把 content_gen 从 deepseek 换成 qwen，上面代码不用动
"""

import os
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════

@dataclass
class ModelConfig:
    """单个模型的配置"""
    provider: str          # "openai_compatible" | "anthropic"
    model: str             # 模型名，如 "deepseek-chat"
    api_key_env: str       # 环境变量名
    base_url: str | None = None
    default_max_tokens: int = 2000
    temperature: float = 0.7
    extra: dict = field(default_factory=dict)


@dataclass
class TaskRoute:
    """任务 → 模型的映射"""
    task: str              # 任务名，如 "content_gen"
    model: str             # 模型名，如 "deepseek-chat"
    priority: int = 0      # 优先级（主模型首选、备选次之）
    condition: str | None = None  # 可选的触发条件表达式


@dataclass
class CallRecord:
    """单次调用的成本记录"""
    model: str
    task: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    cost_usd: float
    timestamp: str
    success: bool
    error: str | None = None


# ══════════════════════════════════════════════════════════════
# CostTracker
# ══════════════════════════════════════════════════════════════

class CostTracker:
    """
    记录每次模型调用的 token 消耗和费用。

    输出 JSONL 日志到 data/cost_log.jsonl，方便后续分析。
    """

    def __init__(self, log_path: str = "data/cost_log.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._pricing: dict[str, dict[str, float]] = {}  # model -> {input, output}

    def register_pricing(self, model: str, input_per_1m: float, output_per_1m: float):
        """注册模型价格（USD / 1M tokens）"""
        self._pricing[model] = {"input": input_per_1m, "output": output_per_1m}

    def record(self, record: CallRecord):
        """记录一次调用"""
        line = json.dumps({
            "model": record.model,
            "task": record.task,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "latency_s": round(record.latency_seconds, 3),
            "cost_usd": round(record.cost_usd, 8),
            "success": record.success,
            "error": record.error,
            "timestamp": record.timestamp,
        }, ensure_ascii=False)

        with open(self.log_path, "a") as f:
            f.write(line + "\n")

    def calc_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """根据模型价格计算费用"""
        price = self._pricing.get(model)
        if not price:
            logger.warning(f"模型 {model} 未注册价格，费用记为 0")
            return 0.0
        return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000

    def summary(self, days: int = 7) -> dict:
        """统计最近 N 天的费用"""
        import datetime
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        total = 0.0
        by_model: dict[str, float] = {}
        by_task: dict[str, float] = {}
        count = 0

        if not self.log_path.exists():
            return {"total_cost": 0.0, "by_model": {}, "by_task": {}, "calls": 0}

        for line in open(self.log_path):
            try:
                r = json.loads(line)
                if r["timestamp"] < cutoff:
                    continue
                cost = r["cost_usd"]
                total += cost
                by_model[r["model"]] = by_model.get(r["model"], 0) + cost
                by_task[r["task"]] = by_task.get(r["task"], 0) + cost
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue

        return {
            "total_cost": round(total, 4),
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
            "by_task": {k: round(v, 4) for k, v in by_task.items()},
            "calls": count,
        }


# ══════════════════════════════════════════════════════════════
# ModelRouter
# ══════════════════════════════════════════════════════════════

class ModelRouter:
    """
    模型路由器：根据任务名自动选择合适的模型。

    使用 OpenAI 兼容格式统一调用所有模型（DeepSeek、通义千问等都兼容）。
    也支持 Anthropic 原生 SDK。

    配置格式见 config/models.yaml
    """

    def __init__(self, config: dict, cost_tracker: CostTracker | None = None):
        self._models: dict[str, ModelConfig] = {}
        self._routes: list[TaskRoute] = []
        self._clients: dict[str, Any] = {}  # 懒加载的客户端
        self.cost_tracker = cost_tracker or CostTracker()

        self._load_config(config)

    @classmethod
    def from_config(cls, config_path: str) -> "ModelRouter":
        """从 YAML 配置文件加载"""
        with open(config_path) as f:
            config = yaml.safe_load(f)
        return cls(config)

    def _load_config(self, config: dict):
        """解析配置"""
        # 加载模型
        for name, cfg in config.get("models", {}).items():
            self._models[name] = ModelConfig(
                provider=cfg["provider"],
                model=cfg["model"],
                api_key_env=cfg["api_key_env"],
                base_url=cfg.get("base_url"),
                default_max_tokens=cfg.get("default_max_tokens", 2000),
                temperature=cfg.get("temperature", 0.7),
                extra=cfg.get("extra", {}),
            )

        # 注册价格
        for name, cfg in config.get("models", {}).items():
            pricing = cfg.get("pricing")
            if pricing:
                self.cost_tracker.register_pricing(
                    name,
                    pricing.get("input_per_1m", 0),
                    pricing.get("output_per_1m", 0),
                )

        # 加载路由规则
        for route_cfg in config.get("routes", []):
            self._routes.append(TaskRoute(
                task=route_cfg["task"],
                model=route_cfg["model"],
                priority=route_cfg.get("priority", 0),
                condition=route_cfg.get("condition"),
            ))

    def _get_client(self, model_key: str):
        """懒加载模型客户端"""
        if model_key in self._clients:
            return self._clients[model_key]

        cfg = self._models[model_key]
        api_key = os.getenv(cfg.api_key_env)
        if not api_key:
            raise ValueError(f"环境变量 {cfg.api_key_env} 未设置")

        if cfg.provider == "openai_compatible":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=cfg.base_url)
        elif cfg.provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(
                api_key=api_key,
                base_url=cfg.base_url,
            )
        else:
            raise ValueError(f"不支持的 provider: {cfg.provider}")

        self._clients[model_key] = client
        return client

    def resolve_model(self, task: str) -> str:
        """根据任务名解析出使用的模型 key"""
        candidates = [r for r in self._routes if r.task == task]
        if not candidates:
            # fallback：用第一个注册的模型
            return next(iter(self._models.keys()))

        # 按优先级排序（数字越小越优先）
        candidates.sort(key=lambda r: r.priority)

        # TODO：后续支持 condition 条件表达式
        return candidates[0].model

    def _call_openai_compatible(self, model_key: str, messages: list, **kwargs) -> dict:
        """通过 OpenAI 兼容接口调用"""
        cfg = self._models[model_key]
        client = self._get_client(model_key)

        response = client.chat.completions.create(
            model=cfg.model,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", cfg.default_max_tokens),
            temperature=kwargs.get("temperature", cfg.temperature),
            tools=kwargs.get("tools"),
        )

        choice = response.choices[0]
        usage = response.usage

        return {
            "content": choice.message.content,
            "tool_calls": choice.message.tool_calls,
            "finish_reason": choice.finish_reason,
            "usage": {
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
            "model": cfg.model,
        }

    def _call_anthropic(self, model_key: str, messages: list, **kwargs) -> dict:
        """通过 Anthropic SDK 调用"""
        cfg = self._models[model_key]
        client = self._get_client(model_key)

        # 转换消息格式：OpenAI -> Anthropic
        system_prompt = None
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                anthropic_messages.append(msg)

        call_kwargs = {
            "model": cfg.model,
            "max_tokens": kwargs.get("max_tokens", cfg.default_max_tokens),
            "messages": anthropic_messages,
        }
        if system_prompt:
            call_kwargs["system"] = system_prompt
        if kwargs.get("tools"):
            call_kwargs["tools"] = kwargs["tools"]

        response = client.messages.create(**call_kwargs)

        text_blocks = [b for b in response.content if b.type == "text"]
        content = "\n".join(b.text for b in text_blocks)

        return {
            "content": content,
            "tool_calls": None,  # Anthropic 的 tool_use 另处理
            "finish_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
            "model": cfg.model,
            "raw": response,  # 保留原始响应，特殊情况用
        }

    def call(
        self,
        task: str,
        messages: list,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: list | None = None,
    ) -> dict:
        """
        统一的模型调用入口。

        Args:
            task: 任务名（如 "content_gen", "review", "analysis"）
            messages: 标准 messages 列表
            max_tokens: 覆盖默认 max_tokens
            temperature: 覆盖默认 temperature
            tools: Function Calling 工具列表

        Returns:
            {"content": str, "usage": {...}, "model": str, ...}
        """
        model_key = self.resolve_model(task)
        cfg = self._models[model_key]

        start = time.time()
        success = True
        error_msg = None

        try:
            kwargs = {}
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if temperature is not None:
                kwargs["temperature"] = temperature
            if tools is not None:
                kwargs["tools"] = tools

            if cfg.provider == "openai_compatible":
                result = self._call_openai_compatible(model_key, messages, **kwargs)
            elif cfg.provider == "anthropic":
                result = self._call_anthropic(model_key, messages, **kwargs)
            else:
                raise ValueError(f"不支持的 provider: {cfg.provider}")

        except Exception as e:
            success = False
            error_msg = str(e)
            result = {
                "content": f"[Error] {error_msg}",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "model": cfg.model,
            }

        latency = time.time() - start
        usage = result["usage"]
        cost = self.cost_tracker.calc_cost(
            model_key, usage["input_tokens"], usage["output_tokens"]
        )

        # 记录成本
        import datetime
        self.cost_tracker.record(CallRecord(
            model=model_key,
            task=task,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            latency_seconds=latency,
            cost_usd=cost,
            timestamp=datetime.datetime.now().isoformat(),
            success=success,
            error=error_msg,
        ))

        result["model_key"] = model_key
        result["cost_usd"] = cost
        result["latency_s"] = round(latency, 3)

        return result


# ══════════════════════════════════════════════════════════════
# 快捷工厂函数
# ══════════════════════════════════════════════════════════════

def create_default_router() -> ModelRouter:
    """创建默认路由器（纯代码配置，不需要 YAML 文件）"""
    config = {
        "models": {
            "deepseek_pro": {
                "provider": "openai_compatible",
                "model": "deepseek-chat",
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com",
                "pricing": {"input_per_1m": 0.435, "output_per_1m": 0.870},
            },
            "deepseek_flash": {
                "provider": "openai_compatible",
                "model": "deepseek-chat",
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com",
                "pricing": {"input_per_1m": 0.14, "output_per_1m": 0.28},
            },
            "qwen_turbo": {
                "provider": "openai_compatible",
                "model": "qwen-turbo",
                "api_key_env": "DASHSCOPE_API_KEY",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "pricing": {"input_per_1m": 0.3, "output_per_1m": 0.6},
            },
        },
        "routes": [
            {"task": "content_gen", "model": "deepseek_pro", "priority": 0},
            {"task": "review_summary", "model": "deepseek_flash", "priority": 0},
            {"task": "data_format", "model": "deepseek_flash", "priority": 0},
            {"task": "analysis", "model": "deepseek_pro", "priority": 0},
            {"task": "strategy", "model": "deepseek_pro", "priority": 0},
            # 备选：主模型挂了自动 fallback
            {"task": "content_gen", "model": "qwen_turbo", "priority": 10},
            {"task": "analysis", "model": "qwen_turbo", "priority": 10},
        ],
    }
    return ModelRouter(config)
