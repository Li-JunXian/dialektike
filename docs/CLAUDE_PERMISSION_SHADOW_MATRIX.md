# Claude Code permission-shadowing contract

Captured: 2026-08-11

Authority: the installed, project-pinned `claude-agent-sdk==0.2.116` typed
contract (`ClaudeAgentOptions`, `CanUseTool`, `PreToolUseHookSpecificOutput`,
and `SandboxSettings`) plus the installed runtime's schema-pinned permission
modes. This is a no-model contract capture; it does not claim that the runtime
can enumerate which inherited rule matched during a turn.

Dialektikḗ's default remains `inherit-native`. The adapter supplies
`can_use_tool`, `PostToolUse`, and `PostToolUseFailure`; its exact SDK override
inputs are `allowed_tools=[]`, `skills=None`, `sandbox=None`, and
`setting_sources=None`. Those values mean no adapter override. In particular,
they do not mean native allowed tools, skills, sandbox configuration, settings
rules, or hooks are absent.

| Mechanism | Effect before `can_use_tool` | Adapter state | Request visible | Effective match visible | SDK warning detects it |
| --- | --- | --- | --- | --- | --- |
| `permission_mode=acceptEdits` | Supported edits may auto-permit | Reviewed `edit-automatically` profile | yes | no | no |
| `permission_mode=auto` | Native classifier may auto-permit or auto-deny | Reviewed `auto` profile | yes | no | no |
| `permission_mode=dontAsk` | Calls not pre-approved by allow rules auto-deny | Reviewed `dont-ask` profile | yes | no | no |
| `permission_mode=bypassPermissions` | All calls except explicit denies bypass the callback | Disabled; separate Live ruling required | yes | no | yes |
| Whole-tool `allowed_tools` entry | Matching calls auto-permit | Adapter input is `[]` | yes | no | yes |
| `skills=all` derived whole-tool `Skill` entry | Skill calls auto-permit | Adapter input is `None`; native discovery may still apply | yes | no | yes |
| Inherited `permissions.defaultMode` setting | The inherited mode may auto-permit or auto-deny | `setting_sources=None` inherits native sources | no | no | no |
| Inherited `permissions.allow` setting | Matching calls auto-permit | `setting_sources=None` inherits native sources | no | no | no |
| Inherited `permissions.deny` setting | Matching calls auto-deny | `setting_sources=None` inherits native sources | no | no | no |
| `PreToolUse` hook returning `allow` or `deny` | Matching calls are resolved before the callback | No adapter PreToolUse hook; inherited hooks are not enumerable | no | no | no |
| `sandbox.autoAllowBashIfSandboxed=true` | Sandboxed Bash calls may auto-permit | Adapter input is `None`; inherited sandbox settings may still apply | no | no | no |

The SDK's `CanUseToolShadowedWarning` is advisory and incomplete: it detects
an explicitly requested `bypassPermissions`, visible whole-tool
`allowed_tools`, and the whole-tool entry derived by `skills=all`. It cannot
detect an inherited `permissions.defaultMode` selecting bypass mode, and it
does not establish the absence of the other paths. Consequently, each turn
records the exact requested SDK input and marks
external allow rules, inherited PreToolUse hooks, sandbox rules, requested
effort, thinking, permission mode, and execution profile as not observable
unless a future runtime supplies authoritative effective-value evidence.

For runtime behavior, an Ask delivered through `can_use_tool` is relayed with
the tool-use correlation identity and is durably exactly-once. A PostToolUse
event whose identity was never delivered through that callback is recorded as
`native_auto_permitted`, without fabricating a permission card. A matching
relayed identity is recorded as `tool_completed` with
`decision_provenance=relayed_approval`; failures retain the corresponding
relayed or native-auto provenance.
