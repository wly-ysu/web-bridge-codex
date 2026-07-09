# Web Tech Lead Routing

## Principle

Codex executes.
ChatGPT Web thinks.

## Default Workflow

User asks natural language question
-> Codex classifies task
-> Non-execution reasoning goes to ChatGPT Web MCP
-> ChatGPT Web returns plan
-> Codex executes plan

## Model Budget Policy

Simple and normal tasks should use GPT-5.5 or the current web model.

Pro / Pro extension quota is limited and should be reserved for rare high-value tasks.

Reserve Pro for:

- 2h+ deep architecture reasoning
- patent / innovation strategy
- autonomous driving safety-critical architecture
- unresolved multi-round failures
- complex cross-module migration strategy
- high-risk final review
- decisions affecting project direction for weeks/months

Avoid Pro for:

- simple explanations
- normal architecture questions
- routine review
- ordinary debug
- formatting
- small code changes
- problems likely solvable within 30 minutes

## Pro Quota Conservation

Rule of thumb:

| Estimated difficulty | Profile | Model priority |
|---|---|---|
| < 5 min | `fast` | GPT-5.5 |
| 5-30 min | `balanced` | GPT-5.5 |
| 30 min-2h | `deep_lite` | GPT-5.5 first |
| 2h+ or strategic | `pro_deep` | Pro first |

User preference:

If user says:

```text
这个留给 Pro
```

then use `pro_deep`.

If user says:

```text
普通5.5就行
```

then avoid Pro.

## Examples

User:
这个模块架构怎么看？

Route:
`ask_pro_architect`
`profile=balanced`

User:
深入分析这个方案，多方案对比一下

Route:
`ask_pro_architect`
`profile=deep_lite`

User:
深度分析这个 freespace GAN 专利方案，留给 Pro

Route:
`ask_pro_architect`
`profile=pro_deep`

User:
review 当前 diff

Route:
`review_pro_code`
`profile=review`

User:
这是合入前关键架构级 review，用 Pro 看一下

Route:
`review_pro_code`
`profile=pro_review`

User:
这个报错怎么修？

Route:
`debug_pro_error`
`profile=debug`

User:
这个异步问题卡了一下午，帮我根因分析

Route:
`debug_pro_error`
`profile=pro_debug`
