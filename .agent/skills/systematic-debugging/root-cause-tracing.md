# Root Cause Tracing

## Overview

Bugs often manifest deep in the call stack. Your instinct is to fix where the error appears, but that's treating a symptom.

**Core principle:** Trace backward through the call chain until you find the original trigger, then fix at the source.

## When to Use

- Error happens deep in execution (not at entry point)
- Stack trace shows long call chain
- Unclear where invalid data originated
- Need to find which test/code triggers the problem

## The Tracing Process

### 1. Observe the Symptom
```
Error: git init failed in /Users/jesse/project/packages/core
```

### 2. Find Immediate Cause
**What code directly causes this?**

### 3. Ask: What Called This?
Trace the call chain upward through the stack.

### 4. Keep Tracing Up
**What value was passed?** Follow the data backward.

### 5. Find Original Trigger
**Where did the bad value come from?**

## Adding Stack Traces

When you can't trace manually, add instrumentation:

```python
import traceback

def problematic_function(directory: str):
    print(f"DEBUG: directory={directory}", file=sys.stderr)
    print(f"DEBUG: cwd={os.getcwd()}", file=sys.stderr)
    traceback.print_stack(file=sys.stderr)
    # ... rest of function
```

**Critical:** Use stderr in tests (stdout may be suppressed)

## Key Principle

**NEVER fix just where the error appears.** Trace back to find the original trigger.

## Stack Trace Tips

- **In tests:** Use stderr, not logger - logger may be suppressed
- **Before operation:** Log before the dangerous operation, not after it fails
- **Include context:** Directory, cwd, environment variables, timestamps
- **Capture stack:** `traceback.print_stack()` shows complete call chain
