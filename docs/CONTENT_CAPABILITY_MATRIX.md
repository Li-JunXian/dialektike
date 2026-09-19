# Safe response-content capability matrix

Status snapshot: 2026-08-11

This matrix records what Dialektikḗ can honestly preserve and render. It does
not promise arbitrary native-client parity. Provider wire formats remain inside
their adapters; shared code consumes only the inert, provider-neutral block
vocabulary in `dialektike/content.py`.

The normalizer now feeds the shared domain, both approved adapters, sidecar and
topic serialization, TypeScript protocol parser, and desktop renderer. That is
transport support, not evidence that every provider emits every row. The
approved Codex and Claude Code descriptors still declare only `markdown`,
matching their currently observed output. A future descriptor can declare more
types through `supported_content_types`; an undeclared emitted type becomes an
inert `unknown` block rather than silently gaining a capability.

## Matrix

| Content | Landed application behavior | Normalizer contract | Remaining fidelity work |
| --- | --- | --- | --- |
| CommonMark / GFM prose | Codex and Claude Code responses traverse the ordered block path as Markdown. The desktop uses `react-markdown`; raw HTML execution is not enabled. | `markdown.text` is copied exactly, including whitespace and Unicode normalization form. | Capture the canonical fixture in packaged light/dark screenshots. |
| Tables | GFM tables render through `remark-gfm`. | Preserved byte-for-byte inside Markdown. | Verify wide-table overflow in both appearances and across the packaged window range. |
| Task lists | GFM task lists render through `remark-gfm`; renderer tests cover the safe GFM path. | Preserved byte-for-byte inside Markdown. | Add the canonical packaged screenshot assertion. |
| Nested backtick and tilde fences | The shared canonical fixture traverses persistence, JSONL, the TypeScript parser, and the Markdown renderer; CommonMark fence parsing and syntax highlighting are present. | Fence characters and line endings are copied exactly, and the copy helper retains an authored terminal newline. | Capture the packaged light/dark rendering. |
| Code | Fenced Markdown code renders with syntax highlighting and a copy control. The shared transport also has a typed code shape, but current provider adapters do not emit it. | `code.code`, optional `language`, and optional `title`; authored strings are unchanged and extra wire fields are discarded. | Map only provider-native code objects that are positively discovered and add adapter/DOM tests. |
| Diffs | The shared transport and desktop have a typed diff presentation; current provider adapters do not emit typed diffs. | `diff.diff` and optional `title`, both inert text. | Add provider mappings and visual/copy tests when native runtimes expose equivalent objects. |
| Mathematics | Markdown math is parsed by `remark-math` and rendered by KaTeX. The shared typed-math transport is present, but no adapter currently emits typed math. | `math.text` plus a boolean `display` (default `true`). | Add a provider mapping only when native typed math is observed, then compare inline/display semantics in light and dark mode. |
| Diagrams | No executable diagram renderer or provider mapping is claimed. | `diagram.source`, `language`, and optional `title` are preserved as inert source. | Choose and security-review a renderer before claiming graphical diagrams; source text must remain the fallback. |
| Citations | The shared typed path can present HTTP(S) citations. Provider-native citation objects are not yet mapped comprehensively. | Requires an authored `label` and an unambiguous absolute HTTP(S) URL. Credentials, controls, whitespace, backslashes, malformed ports, relative URLs, `javascript:`, `data:`, and `file:` are blocked into inert readable text. | Add provider conformance cases and packaged link-opening tests. |
| Files | No provider file action or arbitrary filesystem access is claimed. | Inert `name`, optional `mime_type`, and optional non-negative `size`; URL, path, action, and unapproved asset fields do not cross the boundary. | Define an application-owned ingestion/open-consent flow before files become actionable. |
| Images | No remote provider image fetch or general provider mapping is claimed. The packaged CSP remains `img-src 'self' data:`. | Renderable output requires a per-call application-trusted opaque `asset_id` and a `label`. A model-authored URL/path is never copied, even alongside a trusted ID. | Implement validated local asset ingestion, resolution, consent UI where required, rendering, and appearance/screenshot QA. |
| Audio | No provider audio fetch, playback, or mapping is claimed. | Same trusted-local-asset rule as images; otherwise readable inert fallback. | Implement validated ingestion and accessible local playback before declaring support. |
| Video | No provider video fetch, playback, or mapping is claimed. | Same trusted-local-asset rule as images; otherwise readable inert fallback. | Implement validated ingestion and accessible local playback before declaring support. |
| Tool activity | Dialektikḗ already shows orchestration activity separately. Current provider response adapters do not emit typed tool-result blocks. | Inert `title`, optional `summary`, and optional `status`; no action or raw tool payload crosses. | Map only trustworthy provider-visible summaries; retain raw audit evidence outside user-visible blocks. |
| Editor references | No editor navigation capability is claimed. | Inert `label`, `path`, and optional positive `line`/`column`; URL and action fields are discarded. | Define an explicit application-owned open/navigation policy before making references actionable. |
| Unknown provider content | The domain, JSON wire parser, and renderer now carry a readable inert fallback; real approved adapters currently emit Markdown only. | Produces a readable `unknown` block with a sanitized source-type label and one direct authored display string. It never recursively serializes raw provider objects. | Capture a packaged screenshot and add a real provider mapping only when a provider exposes a positively discovered new type. |

## Canonical UTF-8 fixture

`tests/fixtures/r0-canonical-response.md` is the single R0 conformance fixture.
Its UTF-8 length is 3,783 bytes and its SHA-256 digest is
`51a9b9c21de835584af106221bb10c867101ec0c9acdaa16f2d28c04cbc88330`.
The fixture deliberately contains:

- leading and trailing spaces plus a final newline;
- nested backtick and tilde fences;
- a wide GFM table and task-list markers;
- inline and display mathematics;
- composed and decomposed accented text, case-folding edge cases, and a
  ligature;
- Hebrew and Arabic inside a right-to-left isolate;
- literal HTML, a `javascript:` Markdown link, and a long unbroken wide-text
  run.

The landed no-runtime invariant decodes those bytes strictly, passes the same
provider-mapped Markdown object through the descriptor-driven normalizer for
Codex, Claude Code, and a synthetic future provider, and compares the resulting
UTF-8 bytes. It also verifies block order and input immutability. A transport
invariant then passes the exact fixture through the real Codex and Claude reply
assemblers, a `TopicStore` append and replay, and `topic.read` JSONL
serialization without changing its text or block bytes. The same raw fixture
is imported by the TypeScript parser and renderer tests, which verify its byte
length, trailing spaces/newline, GFM table/task-list and mathematics DOM, and
inert HTML/unsafe-link behavior. The copy-path test proves that an authored
terminal newline is retained. Renderer tests also cover every shared block
variant and hostile URL/HTML fallback. R0 is not fully conformant until the
fixture is captured in packaged light/dark screenshots.

At every textual seam, authored content must be copied rather than trimmed,
Unicode-normalized, case-folded, locale-transformed, or reserialized through an
HTML representation. Derived search normalization is a separate concern and
must never rewrite this canonical text.

## Safety boundary

- The mapper does not execute HTML, resolve a filesystem path, open an editor,
  invoke a tool, or fetch a URL.
- Literal HTML inside Markdown remains authored text. The desktop renderer must
  continue to omit raw-HTML execution; an explicit HTML/script-shaped provider
  block becomes readable `unknown` text.
- Typed-block URLs remain actionable only for citations that pass the
  conservative HTTP(S) check above. Markdown links use the same absolute
  HTTP(S)-only frontend policy. Blocked typed URLs are exposed as text without
  a `url` field, and blocked Markdown targets render without an active link.
- Media trust is application-owned and per call. Provider data cannot declare
  its own asset trustworthy, and CSP allowance for `data:` images does not
  authorize model-authored data URLs.
- Unknown fallback selection is intentionally shallow and allowlisted. Nested
  raw payloads, owner-only evidence, commands, and arbitrary adapter fields are
  not copied into user-visible content.

Any future capability-matrix promotion requires a truthful provider descriptor,
adapter mapping tests, shared protocol tests, safe renderer tests, and packaged
appearance evidence. Merely adding a block name is not support.
