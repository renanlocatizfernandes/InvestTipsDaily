---
name: python-patterns
description: Python development principles and decision-making. Framework selection, async patterns, type hints, project structure. Teaches thinking, not copying.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Python Patterns

> Python development principles and decision-making.
> **Learn to THINK, not memorize patterns.**

---

## How to Use This Skill

This skill teaches **decision-making principles**, not fixed code to copy.

- ASK user for framework preference when unclear
- Choose async vs sync based on CONTEXT
- Don't default to same framework every time

---

## 1. Framework Selection

### Decision Tree

```
What are you building?
│
├── API-first / Microservices → FastAPI (async, modern, fast)
├── Full-stack web / CMS / Admin → Django (batteries-included)
├── Simple / Script / Learning → Flask (minimal, flexible)
├── AI/ML API serving → FastAPI (Pydantic, async, uvicorn)
└── Background workers → Celery + any framework
```

---

## 2. Async vs Sync Decision

### When to Use Async

```
async def is better when:
├── I/O-bound operations (database, HTTP, file)
├── Many concurrent connections
├── Real-time features
└── Microservices communication

def (sync) is better when:
├── CPU-bound operations
├── Simple scripts
├── Legacy codebase
└── Blocking libraries (no async version)
```

### The Golden Rule

```
I/O-bound → async (waiting for external)
CPU-bound → sync + multiprocessing (computing)
```

---

## 3. Type Hints Strategy

### When to Type

```
Always type:
├── Function parameters
├── Return types
├── Class attributes
├── Public APIs

Can skip:
├── Local variables (let inference work)
├── One-off scripts
├── Tests (usually)
```

---

## 4. Project Structure Principles

```
Small project / Script:
├── main.py
├── utils.py
└── requirements.txt

Medium API:
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models/
│   ├── routes/
│   ├── services/
│   └── schemas/
├── tests/
└── pyproject.toml

Large application:
├── src/
│   └── myapp/
│       ├── core/
│       ├── api/
│       ├── services/
│       ├── models/
│       └── ...
├── tests/
└── pyproject.toml
```

---

## 5. Background Tasks

| Solution | Best For |
|----------|----------|
| **BackgroundTasks** | Simple, in-process tasks |
| **Celery** | Distributed, complex workflows |
| **ARQ** | Async, Redis-based |
| **RQ** | Simple Redis queue |
| **Dramatiq** | Actor-based, simpler than Celery |

---

## 6. Error Handling Principles

```
Pattern:
├── Raise domain exceptions in services
├── Catch and transform in handlers
└── Client gets clean error response

Include:
├── Error code (programmatic)
├── Message (human readable)
├── Details (field-level when applicable)
└── NOT stack traces (security)
```

---

## 7. Testing Principles

| Type | Purpose | Tools |
|------|---------|-------|
| **Unit** | Business logic | pytest |
| **Integration** | API endpoints | pytest + httpx/TestClient |
| **E2E** | Full workflows | pytest + DB |

---

## Anti-Patterns to Avoid

### DON'T:
- Default to Django for simple APIs (FastAPI may be better)
- Use sync libraries in async code
- Skip type hints for public APIs
- Put business logic in routes/views
- Ignore N+1 queries
- Mix async and sync carelessly

### DO:
- Choose framework based on context
- Ask about async requirements
- Use Pydantic for validation
- Separate concerns (routes -> services -> repos)
- Test critical paths
