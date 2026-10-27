# Project instructions

- Work only in ~/personal/benefit-monitor. Do not create project files elsewhere or create worktrees.
- Zero additional service spending is a strict user requirement. Never use paid APIs, LLM API calls, subscriptions, trials needing payment details, paid search/browser/SaaS, paid schedulers, paid hosting, or provision cloud resources.
- Do not request or use payment credentials or turn on billing. Never execute purchases, reservations, or benefit applications.
- Use Python standard library, anonymous public official HTTPS pages and local files only.
- Keep HTTP request budget <=100 (default 60). Respect robots, TLS, source allowlists, 6-hour district caches and failure cooldowns. Do not bypass access controls.
- Project cannot guarantee the pricing of ChatGPT/Codex or the user's existing compute/subscription. State that boundary accurately.
- Confirmed facts, application eligibility, remaining inventory and fee status must stay distinct. Never invent dates or mark partial coverage complete.
- Run python -m unittest discover -s tests -v after logic changes.

- "Free" is a requirement for briefing research, generation, infrastructure and delivery costs. It is NOT a filter requiring benefits, events, programs or recruitment to be free.
- Include verified paid events, discounts, purchases with savings, refunds and rewards when relevant. State participation cost, minimum spend, payment/eligibility conditions and uncertain fees explicitly.
- Never prefer or exclude a benefit solely because of fee_status. Keep paid infrastructure integrations forbidden.
