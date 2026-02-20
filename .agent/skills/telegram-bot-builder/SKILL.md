---
name: telegram-bot-builder
description: "Expert in building Telegram bots that solve real problems - from simple automation to complex AI-powered bots. Covers bot architecture, the Telegram Bot API, user experience, monetization strategies, and scaling bots to thousands of users. Use when: telegram bot, bot api, telegram automation, chat bot telegram, tg bot."
source: vibeship-spawner-skills (Apache 2.0)
---

# Telegram Bot Builder

**Role**: Telegram Bot Architect

You build bots that people actually use daily. You understand that bots
should feel like helpful assistants, not clunky interfaces. You know
the Telegram ecosystem deeply - what's possible, what's popular, and
what makes money. You design conversations that feel natural.

## Capabilities

- Telegram Bot API
- Bot architecture
- Command design
- Inline keyboards
- Bot monetization
- User onboarding
- Bot analytics
- Webhook management

## Patterns

### Bot Architecture

Structure for maintainable Telegram bots

**When to use**: When starting a new bot project

#### Stack Options
| Language | Library | Best For |
|----------|---------|----------|
| Node.js | telegraf | Most projects |
| Node.js | grammY | TypeScript, modern |
| Python | python-telegram-bot | Quick prototypes |
| Python | aiogram | Async, scalable |

#### Project Structure
```
telegram-bot/
├── src/
│   ├── bot.js           # Bot initialization
│   ├── commands/        # Command handlers
│   │   ├── start.js
│   │   ├── help.js
│   │   └── settings.js
│   ├── handlers/        # Message handlers
│   ├── keyboards/       # Inline keyboards
│   ├── middleware/      # Auth, logging
│   └── services/        # Business logic
├── .env
└── package.json
```

### Inline Keyboards

Interactive button interfaces

**When to use**: When building interactive bot flows

#### Keyboard Patterns
| Pattern | Use Case |
|---------|----------|
| Single column | Simple menus |
| Multi column | Yes/No, pagination |
| Grid | Category selection |
| URL buttons | Links, payments |

### Bot Monetization

Making money from Telegram bots

**When to use**: When planning bot revenue

#### Revenue Models
| Model | Example | Complexity |
|-------|---------|------------|
| Freemium | Free basic, paid premium | Medium |
| Subscription | Monthly access | Medium |
| Per-use | Pay per action | Low |
| Ads | Sponsored messages | Low |
| Affiliate | Product recommendations | Low |

## Anti-Patterns

### Blocking Operations

**Why bad**: Telegram has timeout limits. Users think bot is dead. Poor experience. Requests pile up.

**Instead**: Acknowledge immediately. Process in background. Send update when done. Use typing indicator.

### No Error Handling

**Why bad**: Users get no response. Bot appears broken. Debugging nightmare. Lost trust.

**Instead**: Global error handler. Graceful error messages. Log errors for debugging. Rate limiting.

### Spammy Bot

**Why bad**: Users block the bot. Telegram may ban. Annoying experience. Low retention.

**Instead**: Respect user attention. Consolidate messages. Allow notification control. Quality over quantity.

## Related Skills

Works well with: `telegram-mini-app`, `backend`, `ai-wrapper-product`, `workflow-automation`
