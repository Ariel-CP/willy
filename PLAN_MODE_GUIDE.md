# Plan Mode Implementation Guide

## Overview

Plan Mode enables Willy to propose multi-step execution plans, get a single user confirmation, and then execute all commands automatically without re-prompting.

## User Flow

```
User: "Create a Python project with requirements.txt and venv"
           ↓
    [AI Thinking...]
           ↓
AI proposes plan:
    "I'll create a Python project for you. Here's my plan:
    
    📋 **Plan:**
    1. Create project directory
    2. Create requirements.txt
    3. Create and activate virtual environment
    4. Install dependencies
    
    Should I proceed with this plan?"
           ↓
User confirms in dialog (single confirmation)
           ↓
AI automatically executes all 4 steps without asking again
    - mkdir project
    - cat > requirements.txt
    - python -m venv .venv
    - source .venv/bin/activate && pip install -r requirements.txt
           ↓
AI reports: "✓ Project created and setup complete!"
```

## Technical Architecture

### 1. System Prompt Enhancement

The `SYSTEM_PROMPT` now includes instructions for "PLAN MODE":
- When user asks for multi-step operations, create a `<plan>` XML structure
- List all steps BEFORE executing any commands
- Wait for confirmation before proceeding

### 2. Plan Detection (in `_process()` loop)

```python
# After AI response received:
if assistant_text and self._has_plan(assistant_text):
    # Show plan to user
    self.on_message("assistant", assistant_text)
    
    # Extract steps
    plan_steps = self._extract_plan_steps(assistant_text)
    
    # Request single confirmation
    if self._request_plan_confirmation(plan_steps):
        # Set 5-minute skip-confirmation window
        self.skip_confirmations_until = time.time() + 300
```

### 3. Automatic Execution

Once confirmed, `_needs_confirmation()` checks the time window:
```python
if time.time() < self.skip_confirmations_until:
    return False  # Skip individual confirmations
```

So commands like `sudo apt-get install` execute immediately without re-prompting.

### 4. Safety Limits

- **Maximum steps per plan**: 15 steps (prevents infinite loops)
- **Confirmation window**: 5 minutes (prevents accidental auto-execution later)
- **Timeout per confirmation**: 120 seconds (prevent UI hang)

## Key Components

### Helper Methods in `AIAgent`

| Method | Purpose |
|--------|---------|
| `_has_plan(text)` | Detect `<plan>` tags in response |
| `_extract_plan_steps(text)` | Parse XML steps into list |
| `_format_plan_display(steps)` | Format steps for user display |
| `_request_plan_confirmation(steps)` | Show dialog, wait for confirmation |
| `_needs_confirmation(command)` | Check if command needs individual confirmation |

### Example Plan XML Format

```xml
<plan>
<step number="1">Create project directory</step>
<step number="2">Initialize git repository</step>
<step number="3">Create requirements.txt</step>
<step number="4">Create .gitignore file</step>
</plan>
```

## Testing

### Unit Tests (Included)
✓ Plan detection  
✓ Plan step extraction  
✓ Plan display formatting  
✓ Confirmation window logic  

### Manual Testing Checklist

- [ ] User asks AI to create a project with multiple steps
- [ ] AI proposes plan with numbered steps
- [ ] Single confirmation dialog appears (not multiple)
- [ ] After confirmation, commands execute without re-prompting
- [ ] Destructive commands (rm, sudo) execute during plan window
- [ ] After 5 minutes, normal confirmation behavior resumes

## Example Prompts to Trigger Plan Mode

1. "Create a Python Flask project with virtual environment"
2. "Set up a Node.js project with npm, ESLint, and Prettier"
3. "Configure an Arduino project and upload a sketch"
4. "Create a backup and organize my file structure"
5. "Initialize a Git repo, commit initial files, and set up remote"

## Configuration

Default behavior (no changes needed):
```json
{
    "confirm_readonly": false,
    "always_confirm": []
}
```

To require confirmation for all commands (including destructive):
```json
{
    "always_confirm": ["rm", "sudo", "mv", "dd"]
}
```

## Troubleshooting

### Plans not being proposed
- Check that user prompt is asking for multi-step operation
- Verify SYSTEM_PROMPT is loaded correctly
- Check AI model (gpt-4o recommended)

### Commands still asking for confirmation
- Check if 5-minute window has elapsed
- Verify `skip_confirmations_until` timestamp
- Check config for `always_confirm` overrides

### Plan format not recognized
- Ensure plan uses exact XML format: `<plan>` ... `</plan>`
- Steps must use format: `<step number="N">Description</step>`
- No nested tags or extra whitespace in step number attribute

## Future Enhancements (v2)

- [ ] Audit logging of executed plans
- [ ] Progress indicator during plan execution
- [ ] Ability to skip/reorder steps in plan
- [ ] Plan templates for common workflows
- [ ] Undo/rollback capability for failed plans
- [ ] Export executed plans to shell script

---

**Implementation Date**: 2026-05-11  
**Status**: ✓ Complete and tested
