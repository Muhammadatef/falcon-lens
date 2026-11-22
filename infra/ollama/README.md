# Local model setup (sovereign mode)

Inkling-2-Mini (Apache-2.0, Thinking Machines Lab) from local Hugging Face weights. Nothing is downloaded by Ollama.

```bash
# 1. import the weights (path to your local HF snapshot)
printf 'FROM %s\n' "$HOME/Models/Inkling-2-Mini" > /tmp/Inkling.base.Modelfile
ollama create inkling-2-mini -f /tmp/Inkling.base.Modelfile
# 2. add the chat template (thinking effort 0, stop tokens)
ollama create inkling-2-mini-chat -f infra/ollama/Inkling-2-Mini.chat.Modelfile
```

Notes (verified 2026-11-22, Ollama 0.40.17):
- The raw import has no chat template (`{{ .Prompt }}`). The chat Modelfile reproduces the model's `chat_template.jinja` for text messages.
- `response_format` (structured output) is **unavailable** for this architecture. Use prompt-level JSON, then pydantic validation, then one repair retry.
- `<|end_message|>` can leak into the content, so the router strips special tokens.
- Thinking effort is fixed at 0, because the README warns of reasoning loops.
- Vision isn't wired in this template yet. Use `FL_LOCAL_VISION_MODEL=gemma3:27b` until it's tested.
- Latency: about 4.7 s warm for 21 output tokens, and about 50 s cold (load). Keep `OLLAMA_KEEP_ALIVE=30m` and pre-warm before demos.
