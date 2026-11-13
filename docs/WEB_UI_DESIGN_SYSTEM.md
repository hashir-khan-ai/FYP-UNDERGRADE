# Web UI Design System — Compliance Desk

**Scope:** `web/` (Next.js 16 workspace)  
**Status:** implemented, build-verified  
**Sources of truth:** `web/styles/tokens.css`, `web/app/globals.css`,
`web/components/ui/*`, `web/lib/modes.ts`, `web/lib/constants.ts`

---

## 1. Design direction

A calm institutional workstation, not a consumer chatbot. Deep navy surfaces,
hairline structure, one blue action accent and a restrained teal verification
accent. Density is closer to a trading terminal than a marketing site, but the
reading column and composer stay generous.

Principles:

1. **Trust is visible.** Role scope, grounding state and source provenance are
   always labelled in text, not implied by colour.
2. **Citations recede until needed.** `Sources (N)` is collapsed by default;
   pipeline telemetry is collapsed a second level down.
3. **One primary action per region.** New session, send, upload, refresh.
4. **Motion explains state.** 120–240 ms, no ambient loops except the trust map.
5. **No dead ends.** Every empty, error and restricted state offers a next step.

### Applied skills

The ten named Figma community resources could not be fetched from this
environment (the pages returned empty responses). The following table records
how each named practice was applied using the local skill guidance
(`skills/frontend-design`, `web-design-guidelines`, `extract-design-system`,
`vercel-react-best-practices`) and the named intent. This is an honest account,
not a claim that the Figma files were read.

| Named skill | Applied in this build |
| :--- | :--- |
| **Better interface** | Replaced Streamlit chrome with a fixed 300 px rail, one reading column, one composer; removed competing accent colours and emoji status noise. |
| **Superfuture design review** | Reviewed every screen against first-principles hierarchy: brand → session → conversation → evidence → telemetry. Deleted decorative panels that did not carry state. |
| **Component handoff** | Every primitive documents props, states, tokens and keyboard behaviour in §5; components live in predictable `ui/`, `chat/`, `workspace/`, `documents/`, `audit/` folders. |
| **Desktop to mobile** | Sidebar becomes a Radix dialog drawer under `lg`; tables become cards; composer/header switch to safe-area-aware heights; reading width collapses to full width. |
| **Create anatomy** | Chat turn, citation card, session row, KPI tile and upload dialog each have an explicit anatomy list in §5. |
| **Find animation opportunities** | Motion inventory in §6: state changes, entrances, progressive reveal, caret, trust-map pulse; everything reduced-motion safe. |
| **Spacing audit** | 4 pt rhythm audit in §4, including header/composer/rail measurements and a list of intentional exceptions. |
| **Balise UX writing** | Voice and copy decisions in §7: role-aware, specific, no hype, no blame, no fabricated certainty. |
| **Analyze components** | Component inventory in §5 separates primitives, composites and page regions; duplicates were merged (one Button, one Badge, one Dialog). |
| **Design system generation** | Tokens → Tailwind theme → primitives → composites → pages, with semantic names only (`--surface`, `--line`, `--accent`, `--warning`). |

---

## 2. Colour tokens

All values are in `web/styles/tokens.css`; Tailwind exposes them through
`@theme inline` in `globals.css`.

| Token | Value | Use |
| :--- | :--- | :--- |
| `--canvas` | `#070b11` | App background |
| `--canvas-raised` | `#090e15` | Dialogs, sticky table heads |
| `--surface` | `#0d131c` | Cards, message surfaces |
| `--surface-2` | `#111925` | Inputs, secondary buttons, hover rows |
| `--surface-3` | `#162130` | Active segmented control |
| `--line` | `rgba(164,184,212,0.12)` | Default hairline |
| `--line-strong` | `rgba(164,184,212,0.22)` | Input hover, dialog edge |
| `--line-accent` | `rgba(120,169,255,0.36)` | Focus/active border |
| `--ink` | `#f3f6fa` | Primary text |
| `--ink-soft` | `#d9e1eb` | Dense body text |
| `--muted` | `#a4afbf` | Secondary text |
| `--faint` | `#7f8b9d` | Metadata, captions |
| `--accent` | `#78a9ff` | Primary action, focus, links |
| `--accent-strong` | `#4f8df7` | Primary hover |
| `--accent-ink` | `#06101d` | Text on primary |
| `--teal` | `#54d6c4` | Verification / source trust |
| `--success` | `#56d99b` | Grounded, online |
| `--warning` | `#f0c36a` | Refusal, non-demo profile |
| `--danger` | `#ff8585` | Errors, destructive actions |
| `--non-grounded` | `#c1a8ff` | Open-knowledge badge |

Colour is never the only signal: badges pair tone with text and an icon.

---

## 3. Typography

- UI stack: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
  "Helvetica Neue", Arial, sans-serif`. No webfont request.
- Mono stack: `"SF Mono", ui-monospace, Menlo, Monaco, Consolas, monospace`.
- Scale: 11 / 12 / 13 / 15 / 16 / 18 / 22 / 28 / 36 / 46 px
  (`--text-2xs` … `--text-4xl`).
- Body 15 px / 1.55; answer prose 15.2 px / 1.72 with `overflow-wrap: anywhere`.
- Headings use tight tracking (`-0.02em` to `-0.035em`) and balanced wrapping.
- Numeric telemetry uses `font-variant-numeric: tabular-nums` via `.tabular`.

---

## 4. Spacing audit

Base rhythm: **4 pt**. Named steps: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80.

| Region | Measurement | Rationale |
| :--- | :--- | :--- |
| Desktop sidebar | `300px` | Matches legacy contract; fits session titles + role chip |
| Mobile drawer | `min(88vw, 340px)` | Leaves a visible scrim edge to signal dismissal |
| Chat/composer reading width | `768px` | ~75–85 characters at 15 px |
| Documents/audit content | full width, `16/24/40px` gutters | Tables need room; gutters grow with viewport |
| Chat header | `56px` | Native toolbar height; aligns with mobile top bar |
| Mobile top bar | `56px` | Same rhythm as desktop header |
| Composer outer padding | `12px` mobile, `20px` tablet, `32px` desktop | Keeps thumb target clear of edge |
| Composer textarea | min `44px`, max `168px` | One-line start, ~6 lines before scroll |
| Message vertical rhythm | `20px` between turns, `8–12px` inside a turn | Separates speakers without cards-in-cards |
| Citation card padding | `14px` | Dense evidence, still scannable |
| Dialog header/footer | `20px` horizontal, `14px` footer vertical | Consistent with card padding |
| Table cell | `12px` horizontal, `10px` vertical | Fits 5–7 columns at 1280 px |
| Icon buttons | `28px` / `36px` | 28 px compact rows, 36 px primary actions |
| Sidebar session row | `~48px` | Two lines: title + relative time |

Intentional exceptions:

- Trust map uses an SVG viewBox rather than the 4 pt grid; optical spacing is
  hand-tuned and scales with width.
- The progressive caret uses `0.12em` offsets to sit on the text baseline.
- KPI values use 18 px with 2 px of extra top space for optical centring.

---

## 5. Component inventory & anatomy

### Primitives (`web/components/ui/`)

| Component | Anatomy | States / notes |
| :--- | :--- | :--- |
| `Button` | root → optional leading icon → label → optional trailing icon | `primary`, `secondary`, `outline`, `ghost`, `soft`, `danger`; `sm/md/lg/icon/icon-sm`; `asChild` clones a child without a context Slot so Server Components can import it |
| `Input` / `Textarea` / `Label` | label → control → optional hint/error | hover, focus ring, disabled; explicit labels everywhere |
| `Badge` | optional icon → text | `neutral`, `accent`, `success`, `warning`, `danger`, `info`, `nonGrounded`, `outline` |
| `Card` | surface → header → content → footer | Used for KPIs and grouped settings, not for every message |
| `Dialog` | overlay → content → header/title/description → body → footer → close | Focus trap and Escape handled by Radix; mobile drawer overrides geometry |
| `DropdownMenu` | trigger → content → label/item/separator | Used for session actions and account menu |
| `Collapsible` | trigger → content | Sources and pipeline details are collapsed by default |
| `SegmentedControl` | radiogroup → radio buttons | Arrow-key roving focus, `aria-checked`, visible active state |
| `Tooltip` | trigger → portal content | 220 ms delay; explanatory only, never sole label |
| `Avatar` | initials in a bordered circle | No remote image, no personal photo |
| `Progress` | track → fill | Determinate or indeterminate; `role="progressbar"` |
| `Skeleton` | shimmer block | Used by route-level loading and lazy trust map |

### Composites

**Chat turn** (`components/chat/message-list.tsx`)

1. Speaker marker (user bubble or assistant shield)
2. Grounding badge: `Grounded in permitted documents` / `Open knowledge · not grounded` / `Refusal`
3. Route + time + copy/regenerate actions
4. Answer prose, refusal card, or progressive reveal
5. Collapsed `Sources (N)`
6. Suggested follow-up chips
7. Collapsed `Pipeline details`

**Citation card**

1. Ordinal
2. Document title
3. Trust badge: authority name, or `Internal`
4. Heading / clause / page / source identifier definition list
5. Verbatim snippet in a left-ruled quote
6. Safe actions: `Open source`, `Verify on Google`, or internal-only note

**Composer**

1. Scope segmented control (`Auto`, `Company docs`, `General`)
2. Response style (`Strict`, `Explain`)
3. Auto-growing textarea
4. Keyboard hints + character guard
5. Mode tooltip + circular send button
6. Server-side RBAC reassurance line

**Session row**

1. Title (truncated)
2. Relative activity time
3. Overflow menu: rename, delete
4. Inline rename field with save/cancel
5. Delete confirmation dialog

**Upload dialog**

1. Drop zone / file picker
2. Title + optional document ID
3. Document type + read-access role chips
4. Indeterminate upload → determinate indexing progress
5. Success receipt with `doc_id` and chunk count
6. Sanitised error alert

**KPI tile** (audit)

1. Label + icon
2. Tabular value
3. Explanatory hint (never a bare number)

**Trust map** (`components/visual/trust-map.tsx`)

1. Corpus node
2. Role gate node
3. Relevance grader node
4. Verified answer node
5. Dashed safe-refusal node
6. Travelling verification pulse (disabled for reduced motion)
7. Pointer tilt capped at ±4°/±6°, disabled for reduced motion

### Handoff notes

- Tokens are semantic; do not introduce raw hex values in components.
- All interactive elements have visible `:focus-visible` outlines (2 px accent,
  2 px offset) and a text label or `aria-label`.
- New API fields must be added to `web/lib/types.ts` and, if persisted, to
  `MessageMetadata`. Reload parity depends on metadata, not in-memory state.
- Do not render a URL without passing it through `safeHttpUrl` in
  `web/lib/citations.ts`.
- Do not add a client-side role switch. Role comes from the server session.

---

## 6. Motion inventory

| Moment | Treatment | Duration / easing |
| :--- | :--- | :--- |
| New turn entrance | 8 px rise + fade | 240 ms `cubic-bezier(0.22,1,0.36,1)` |
| Hover lift (cards, persona) | 1–2 px translate | 180 ms |
| Segmented control | background/colour crossfade | 120 ms |
| Progressive answer | character reveal | 280–900 ms total, capped |
| Streaming caret | 1 s step blink | only while revealing |
| Thinking stages | spinner + check transitions | 180 ms |
| Collapsible | content mount + 8 px rise | 240 ms |
| Trust pulse | 5.2 s path animation | disabled under reduced motion |
| Skeleton | 1.8 s shimmer | disabled under reduced motion |

`@media (prefers-reduced-motion: reduce)` clamps all animations/transitions to
`0.01ms`, disables smooth scrolling, and freezes the trust map. The progressive
reveal checks `matchMedia` in JavaScript and renders the full answer immediately.

Motion is never used to hide loading or to fake work: the status list reflects
real request phases, and the reveal begins only after the verified answer arrives.

---

## 7. UX writing decisions

**Voice:** precise, calm, second person, no exclamation marks, no “AI magic”.
The product is a compliance instrument, so uncertainty is stated explicitly.

| Context | Copy | Why |
| :--- | :--- | :--- |
| Product name | `Compliance Desk` | Short, institutional, not “chatbot” |
| Login headline | “Regulatory answers you can defend.” | Outcome + auditability |
| Persona helper | “Quick-fill sets the username only…” | Honest about the security choice |
| Scope labels | `Auto` / `Company Docs RAG` / `General Chat` | Matches backend `intent_mode`; no invented modes |
| Grounded badge | “Grounded in permitted documents” | Names both grounding and role scope |
| Non-grounded badge | “Open knowledge · not grounded” | Prevents mistaking general chat for policy |
| Refusal title | “No permitted source supports this answer” | Explains the refusal without blaming the user |
| Refusal footer | “The assistant refuses rather than inventing a passage or revealing a restricted source.” | States the safety behaviour |
| Sources trigger | `Sources (N)` | Compact, count is visible before expansion |
| Internal citation | “Internal document — no public verification link” | Explains the missing action |
| External actions | “Open source” / “Verify on Google” | Distinguishes canonical link from a search |
| Upload gate | “Upload requires Manager or Auditor” | States the rule, not just “disabled” |
| Analyst audit gate | “Audit summaries are restricted” | Avoids implying the data is missing |
| Error title | “The answer could not be completed” | No stack traces, no blame |
| Retry | “Try again” | Short, action-first |
| Offline | “Offline — reconnect to send.” | Explains why send is blocked |
| Empty sessions | “No sessions yet” + next step | No dead end |

Avoided: “Sorry!”, “Oops”, “As an AI…”, “100% accurate”, “bank-grade”,
“unhackable”, and any claim that UI hiding equals authorisation.

---

## 8. Accessibility

- Skip link to `#main`.
- Semantic landmarks: `header`, `nav`, `main`, `aside`, `footer` regions.
- `role="log"` on the conversation, `role="status"` + `aria-live="polite"` on
  pipeline stages, `role="alert"` on errors.
- Dialogs have titles/descriptions (some visually hidden for the drawer).
- Segmented controls use `role="radiogroup"` / `role="radio"`, arrow keys and
  roving `tabIndex`.
- All icon-only buttons have `aria-label` and `title`.
- Tables use `scope="col"` headers and sticky header rows.
- Minimum target size: 28 px compact, 36–44 px primary.
- Contrast: body text `#f3f6fa` on `#070b11` is > 15:1; muted `#a4afbf` on
  `#0d131c` is > 7:1; accent text on dark surfaces exceeds 4.5:1.

---

## 9. Responsive rules

| Breakpoint | Behaviour |
| :--- | :--- |
| `< 640px` | Single column; cards stack; header compresses to title + status; composer hints shorten |
| `640–1023px` | Sidebar still hidden; starter cards in 3 columns; tables become cards |
| `≥ 1024px` | Fixed 300 px sidebar; chat and composer use the 768 px reading column; document tables appear |
| `≥ 1280px` | Audit KPIs in 4 columns; catalog table gains breathing room |

The desktop→mobile pass keeps the same information order: identity → scope →
conversation/evidence → telemetry. Nothing is hidden solely for space except
secondary hints and the desktop table representation.
