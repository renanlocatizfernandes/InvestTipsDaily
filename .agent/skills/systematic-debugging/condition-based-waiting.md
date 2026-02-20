# Condition-Based Waiting

## Overview

Flaky tests often guess at timing with arbitrary delays. This creates race conditions where tests pass on fast machines but fail under load or in CI.

**Core principle:** Wait for the actual condition you care about, not a guess about how long it takes.

## When to Use

- Tests have arbitrary delays (setTimeout, sleep, time.sleep())
- Tests are flaky (pass sometimes, fail under load)
- Tests timeout when run in parallel
- Waiting for async operations to complete

## Core Pattern

```python
# BAD: Guessing at timing
import time
time.sleep(0.5)
result = get_result()
assert result is not None

# GOOD: Waiting for condition
import time

def wait_for(condition, description, timeout=5.0, interval=0.01):
    start = time.monotonic()
    while True:
        result = condition()
        if result:
            return result
        if time.monotonic() - start > timeout:
            raise TimeoutError(f"Timeout waiting for {description} after {timeout}s")
        time.sleep(interval)

wait_for(lambda: get_result() is not None, "result to be available")
result = get_result()
assert result is not None
```

## Quick Patterns

| Scenario | Pattern |
|----------|---------|
| Wait for event | `wait_for(lambda: events.find(type='DONE'))` |
| Wait for state | `wait_for(lambda: machine.state == 'ready')` |
| Wait for count | `wait_for(lambda: len(items) >= 5)` |
| Wait for file | `wait_for(lambda: os.path.exists(path))` |

## Common Mistakes

- **Polling too fast:** `sleep(0.001)` — wastes CPU. Use 10ms intervals.
- **No timeout:** Loop forever if condition never met. Always include timeout.
- **Stale data:** Cache state before loop. Call getter inside loop for fresh data.

## When Arbitrary Timeout IS Correct

Requirements:
1. First wait for triggering condition
2. Based on known timing (not guessing)
3. Comment explaining WHY
