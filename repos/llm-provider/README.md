# llm-provider — LLM Provider 抽象层

多厂商 LLM 统一适配层，支持 DeepSeek / 通义千问 / 智谱 GLM / Anthropic 四家 API，一行配置即可切换 provider。

## 架构

```
LLMProviderManager (路由)
├── DeepSeekAdapter   (文本 LLM 主力, OpenAI 兼容)
├── QwenAdapter       (多模态 VL + Embedding)
├── GLMAdapter        (多模态备用)
└── AnthropicAdapter  (Dev Agent 专用)
```

## 快速开始

```python
from llm_provider import LLMProviderManager
import yaml

with open('llm_provider/config.yaml') as f:
    config = yaml.safe_load(f)

mgr = LLMProviderManager(config)
resp = await mgr.chat(messages=[{"role":"user","content":"你好"}], task_type="text")
print(resp.content)
```

## 配置切换

修改 `llm_provider/config.yaml` 中的 routing 即可切换 provider：
- `routing.text: deepseek` → `routing.text: anthropic`

## 环境变量

- `DEEPSEEK_API_KEY`
- `QWEN_API_KEY`
- `GLM_API_KEY`
- `ANTHROPIC_API_KEY`

## 关联 Spec

spec-19 · LLM Provider 抽象层
