# Defense-in-Depth Validation

## Overview

When you fix a bug caused by invalid data, adding validation at one place feels sufficient. But that single check can be bypassed by different code paths, refactoring, or mocks.

**Core principle:** Validate at EVERY layer data passes through. Make the bug structurally impossible.

## Why Multiple Layers

Single validation: "We fixed the bug"
Multiple layers: "We made the bug impossible"

Different layers catch different cases:
- Entry validation catches most bugs
- Business logic catches edge cases
- Environment guards prevent context-specific dangers
- Debug logging helps when other layers fail

## The Four Layers

### Layer 1: Entry Point Validation
**Purpose:** Reject obviously invalid input at API boundary

### Layer 2: Business Logic Validation
**Purpose:** Ensure data makes sense for this operation

### Layer 3: Environment Guards
**Purpose:** Prevent dangerous operations in specific contexts

### Layer 4: Debug Instrumentation
**Purpose:** Capture context for forensics

## Applying the Pattern

When you find a bug:

1. **Trace the data flow** — Where does bad value originate? Where used?
2. **Map all checkpoints** — List every point data passes through
3. **Add validation at each layer** — Entry, business, environment, debug
4. **Test each layer** — Try to bypass layer 1, verify layer 2 catches it

## Key Insight

All four layers are necessary. During testing, each layer catches bugs the others miss:
- Different code paths bypass entry validation
- Mocks bypass business logic checks
- Edge cases on different platforms need environment guards
- Debug logging identifies structural misuse

**Don't stop at one validation point.** Add checks at every layer.
