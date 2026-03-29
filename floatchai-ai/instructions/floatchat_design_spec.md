# FloatChat — Design Specification
## Frontend Visual Language & Design System

**Version:** 1.0
**Applies To:** All frontend features (Feature 5 through Feature 10)
**Must Be Read Before:** Any frontend scaffold, Tailwind config, shadcn init, or component work

---

## 1. Design Philosophy

FloatChat is a research tool for oceanographers, climate analysts, and students. The interface must feel **approachable and welcoming** — not cold or clinical like a traditional scientific dashboard. Researchers spend hours inside this tool. It should feel like the ocean itself: calm, beautiful, and trustworthy.

The guiding principle is **quiet ocean presence**. The interface should evoke the feeling of sitting at the shore — light, open, and clear in day mode; serene, mysterious, and focused in night mode. The ocean is never aggressive or loud. Neither is this UI.

Subtle background textures and illustrations reinforce the oceanic identity without competing with the data. Charts, tables, and query results are always the visual priority. The ocean aesthetic is the backdrop, not the foreground.

---

## 2. Color System

### 2.1 Light Mode — Tropical Coast

Inspired by a warm, sunlit tropical shoreline. Warm sand, turquoise water, bright foam, clear sky.

#### Semantic Color Tokens (CSS Variables)

```
--color-bg-base          #F5F0E8    Warm sand — main page background
--color-bg-surface       #FDFAF4    Foam white — cards, panels, chat bubbles
--color-bg-elevated      #FFFFFF    Pure white — modals, dropdowns, popovers
--color-bg-subtle        #EDE8DD    Darker sand — sidebar background, input bg

--color-border-default   #D4C9B5    Sand border — dividers, input borders
--color-border-subtle    #E8E2D6    Light sand — subtle separators

--color-text-primary     #1A2E35    Deep ocean dark — main body text
--color-text-secondary   #4A6572    Slate water — secondary labels, metadata
--color-text-muted       #7A9099    Pale water — placeholder text, disabled
--color-text-inverse     #FDFAF4    Foam white — text on dark backgrounds

--color-ocean-primary    #1B7A9E    Ocean blue — primary actions, links, active states
--color-ocean-light      #4BAAC8    Sky blue — hover states, highlights
--color-ocean-lighter    #A8D8E8    Pale sky — selected backgrounds, chips
--color-ocean-deep       #0D4F6B    Deep water — pressed states, dark accents

--color-sky              #87CEEB    Sky blue — informational states, tags
--color-coral            #E8785A    Warm coral — warnings, attention
--color-seafoam          #7ECBA3    Sea foam green — success states
--color-danger           #D94F3D    Red tide — errors, destructive actions

--color-accent-sand      #C9A96E    Golden sand — accent highlights, badges
```

#### Usage Rules — Light Mode
- Page background is always `--color-bg-base` (warm sand). Never pure white.
- Cards and panels use `--color-bg-surface` (foam white). This creates a subtle warm lift off the background.
- The sidebar uses `--color-bg-subtle` (darker sand) to visually separate it from the main content area.
- All primary buttons, links, and interactive elements use `--color-ocean-primary`.
- Never use pure `#000000` black for text. `--color-text-primary` is a very dark ocean teal, not pure black.

---

### 2.2 Dark Mode — Moonlit Shore

Inspired by the ocean at night under a full moon. Dark water, silver-blue moonlight on the surface, hints of deep purple in the depths.

#### Semantic Color Tokens (CSS Variables)

```
--color-bg-base          #0B1220    Deep midnight navy — main page background
--color-bg-surface       #131D2E    Dark ocean — cards, panels, chat bubbles
--color-bg-elevated      #1C2840    Slightly lighter navy — modals, dropdowns
--color-bg-subtle        #0D1628    Darker than base — sidebar background

--color-border-default   #253348    Moonlit water — dividers, input borders
--color-border-subtle    #1A2A3D    Dark border — subtle separators

--color-text-primary     #E8EEF4    Moonlit white — main body text
--color-text-secondary   #8BA5BC    Silver water — secondary labels, metadata
--color-text-muted       #526A80    Deep water muted — placeholder text, disabled
--color-text-inverse     #0B1220    Dark text — text on light backgrounds

--color-ocean-primary    #4BAAC8    Sky reflection — primary actions, links, active states
--color-ocean-light      #7FCCE0    Bright moonlit water — hover states
--color-ocean-lighter    #1E3A4F    Dark teal tint — selected backgrounds
--color-ocean-deep       #2D7A9A    Mid-depth — pressed states

--color-moon-silver      #B8C8D8    Moonlight silver — decorative accents, shimmer
--color-deep-purple      #2A1F3D    Abyssal purple — subtle depth in backgrounds
--color-coral            #E8785A    Bioluminescent warm — warnings, attention
--color-seafoam          #5BA882    Phosphorescence green — success states
--color-danger           #C94040    Deep red — errors, destructive actions

--color-accent-moon      #7B9DB8    Moon reflection — accent highlights, badges
```

#### Usage Rules — Dark Mode
- Background is `--color-bg-base` — a very deep midnight navy, not pure black. Pure black feels dead. This has life.
- The deep purple (`--color-deep-purple`) appears only as subtle depth in the background — applied via the background texture/gradient, not as a block color.
- The sidebar is `--color-bg-subtle` — slightly darker than the base to recede.
- Primary actions use `--color-ocean-primary` (sky reflection) — the same hue as light mode but luminous against the dark background.
- Silver (`--color-moon-silver`) is used sparingly for decorative shimmer effects on the background illustration.

---

## 3. Typography

### 3.1 Font Families

**Display / Headings: `Fraunces`**
A variable optical-size serif with a warm, slightly nautical character. Has beautiful ink trap details that feel organic and coastal. Used for the FloatChat wordmark, page titles, and empty state headings. Available on Google Fonts.

**Body / UI: `DM Sans`**
A clean, geometric sans-serif with a friendly, open quality. Excellent legibility at small sizes for data-dense interfaces. Approachable without being playful. Available on Google Fonts.

**Monospace / Code / SQL: `JetBrains Mono`**
For the collapsible SQL display in chat messages and any code blocks. Tight, readable, professional. Available on Google Fonts.

### 3.2 Type Scale

```
--font-display     Fraunces, Georgia, serif
--font-body        "DM Sans", system-ui, sans-serif
--font-mono        "JetBrains Mono", "Courier New", monospace

--text-xs          0.75rem   /  1.25  (12px) — timestamps, metadata, labels
--text-sm          0.875rem  /  1.5   (14px) — secondary body, captions
--text-base        1rem      /  1.6   (16px) — primary body text
--text-lg          1.125rem  /  1.5   (18px) — message content
--text-xl          1.25rem   /  1.4   (20px) — section headings
--text-2xl         1.5rem    /  1.3   (24px) — page titles
--text-3xl         2rem      /  1.2   (32px) — display headings (Fraunces)
--text-4xl         2.5rem    /  1.1   (40px) — hero / wordmark

--font-normal      400
--font-medium      500
--font-semibold    600
--font-bold        700
```

### 3.3 Typography Rules
- The FloatChat wordmark uses `Fraunces` at `--text-3xl` or larger, `--font-semibold`
- Section headings in the sidebar and dashboard use `DM Sans` `--font-semibold`
- Chat message content uses `DM Sans` at `--text-base` with `--font-normal`
- SQL blocks use `JetBrains Mono` at `--text-sm`
- Timestamps and metadata always use `--text-xs` and `--color-text-muted`
- Never mix display font with mono. Fraunces is for headings and brand only.

---

## 4. Spacing & Layout

### 4.1 Spacing Scale
Uses a base-4 system.

```
--space-1    0.25rem   (4px)
--space-2    0.5rem    (8px)
--space-3    0.75rem   (12px)
--space-4    1rem      (16px)
--space-5    1.25rem   (20px)
--space-6    1.5rem    (24px)
--space-8    2rem      (32px)
--space-10   2.5rem    (40px)
--space-12   3rem      (48px)
--space-16   4rem      (64px)
```

### 4.2 Border Radius

```
--radius-sm     0.25rem   (4px)   — inline badges, chips
--radius-md     0.5rem    (8px)   — buttons, inputs, small cards
--radius-lg     0.75rem   (12px)  — cards, panels, dropdowns
--radius-xl     1rem      (16px)  — large cards, chat bubbles
--radius-2xl    1.5rem    (24px)  — modals, floating panels
--radius-full   9999px            — pills, avatar, fully rounded
```

### 4.3 Layout Dimensions

```
Sidebar width (expanded):    280px
Sidebar width (collapsed):   64px (icon-only on mobile)
Chat input max height:       144px (6 lines)
Chat thread max width:       720px (centered in the main panel)
Dashboard grid columns:      3 (lg), 2 (md), 1 (sm)
Top navigation height:       0px (no top nav — sidebar-only layout)
```

### 4.4 Elevation / Shadow

Light mode shadows use warm sand undertones. Dark mode shadows use deep navy.

```
--shadow-sm      Light mode: 0 1px 3px rgba(26, 46, 53, 0.08)
                 Dark mode:  0 1px 3px rgba(0, 0, 0, 0.3)

--shadow-md      Light mode: 0 4px 12px rgba(26, 46, 53, 0.10)
                 Dark mode:  0 4px 12px rgba(0, 0, 0, 0.4)

--shadow-lg      Light mode: 0 8px 24px rgba(26, 46, 53, 0.12)
                 Dark mode:  0 8px 24px rgba(0, 0, 0, 0.5)
```

---

## 5. Background Illustration System

This is what gives FloatChat its identity. The background illustrations are **subtle, non-distracting, and purely atmospheric**. They are never more prominent than the content in front of them.

### 5.1 Illustration Style
SVG-based wave and horizon illustrations. Organic, flowing shapes. No photographic images — everything is vector so it scales perfectly and stays lightweight. The illustrations sit at very low opacity behind the UI, functioning as texture rather than imagery.

### 5.2 Light Mode Background
The main page background (`--color-bg-base`) is augmented with:
- A very faint SVG wave pattern at the bottom of the viewport — two or three gentle wave curves in `--color-ocean-lighter` at 15–20% opacity
- A subtle radial gradient in the top-right quadrant suggesting a sky/sun softness — from `#FFFFFF` at the top to `--color-bg-base` downward
- The wave pattern is fixed-position (does not scroll with content)

The overall effect: you are sitting above the shoreline looking down slightly. The data is on the desk in front of you. The ocean is visible through the window behind.

### 5.3 Dark Mode Background
The main page background augmented with:
- A multi-layer gradient: `--color-bg-base` (midnight navy) as base, with a very subtle wash of `--color-deep-purple` bleeding up from the bottom-left at 30% opacity
- A faint SVG wave silhouette at the bottom of the viewport — gentle, dark waves in `#1A2840` at 40% opacity against the slightly lighter background above them
- A soft radial glow in the top-center suggesting a moon — a `radial-gradient` from `rgba(184, 200, 216, 0.04)` to transparent, approximately 600px diameter
- The wave pattern is fixed-position

The overall effect: you are standing at the water's edge at night. The moon is above. The ocean is dark and present but calm.

### 5.4 Illustration Placement Rules
- All illustration layers must be in a fixed, non-interactive `div` behind all content with `pointer-events: none` and `z-index: 0`
- Content always has `z-index: 1` or higher
- Illustrations must never appear inside modals, dropdowns, or chart components — only on the page background
- On the login/signup pages, the illustration may be more prominent (slightly higher opacity, larger waves) since there is less competing content
- In the chat thread area specifically, the background behind the thread is `--color-bg-surface` (not base), so the wave illustration only shows in the sidebar and the margins around the thread

---

## 6. Component Style Guide

### 6.1 Buttons

**Primary Button**
Background: `--color-ocean-primary`. Text: `--color-text-inverse`. Border-radius: `--radius-md`. Font: `DM Sans` `--font-medium`. Hover: `--color-ocean-light`. Active: `--color-ocean-deep`. Focus ring: 2px offset, `--color-ocean-light`.

**Secondary Button**
Background: transparent. Border: 1.5px solid `--color-border-default`. Text: `--color-text-primary`. Hover background: `--color-bg-subtle`. Radius: `--radius-md`.

**Ghost Button**
No border, no background. Text: `--color-text-secondary`. Hover: `--color-bg-subtle`. Used for icon buttons and low-emphasis actions.

**Destructive Button**
Background: `--color-danger`. Text: white. Hover: slightly darker. Used for delete confirmations only.

### 6.2 Inputs & Textareas

Background: `--color-bg-elevated`. Border: 1.5px solid `--color-border-default`. Border-radius: `--radius-md`. Focus: border color changes to `--color-ocean-primary`, `box-shadow: 0 0 0 3px rgba(27, 122, 158, 0.15)` in light / `rgba(75, 170, 200, 0.2)` in dark. Placeholder: `--color-text-muted`. Padding: `--space-3 --space-4`.

The chat input textarea has a slightly more prominent focus state with a stronger box shadow to indicate the primary interaction area.

### 6.3 Cards & Panels

Background: `--color-bg-surface`. Border: 1px solid `--color-border-subtle`. Border-radius: `--radius-lg`. Shadow: `--shadow-sm`. No border in dark mode — elevation is conveyed through background color difference alone.

### 6.4 Chat Bubbles

**User message:** Background `--color-ocean-primary`, text `--color-text-inverse`. Border-radius: `--radius-xl` with the bottom-right corner at `--radius-sm` (directional tail effect). Aligned right. Max width 70% of thread width.

**Assistant message:** Background `--color-bg-surface`. Border: 1px solid `--color-border-subtle`. Border-radius: `--radius-xl` with the bottom-left corner at `--radius-sm`. Aligned left. Max width 85% of thread width (wider to accommodate tables and charts).

### 6.5 Follow-Up Chips

Background: `--color-ocean-lighter`. Border: 1px solid `--color-ocean-light`. Text: `--color-ocean-deep` in light / `--color-ocean-light` in dark. Border-radius: `--radius-full`. Font: `--text-sm` `--font-medium`. Hover: background `--color-ocean-light`, text `--color-text-inverse`.

### 6.6 Session Sidebar Items

Default: text `--color-text-secondary`. Hover: background `--color-bg-elevated`, text `--color-text-primary`. Active: background `--color-ocean-lighter` in light / `--color-ocean-lighter` in dark, text `--color-ocean-primary`, left border 3px solid `--color-ocean-primary`.

### 6.7 The FloatChat Wordmark

Rendered in `Fraunces` `--font-bold` at the top of the sidebar. In light mode: `--color-ocean-deep`. In dark mode: `--color-moon-silver`. Optionally preceded by a small wave icon from `lucide-react` (`Waves` icon) in `--color-ocean-primary`. No complex logo — the typography is the identity.

---

## 7. Motion & Animation

Keep motion subtle and purposeful. The ocean is calm — the animations should be too.

```
--duration-fast      100ms    — button press feedback
--duration-normal    200ms    — hover transitions, focus rings
--duration-slow      300ms    — panel slides, modal enter
--duration-slower    500ms    — page transitions, large reveals

--ease-default       cubic-bezier(0.4, 0, 0.2, 1)    — standard smooth
--ease-in            cubic-bezier(0.4, 0, 1, 1)       — elements leaving
--ease-out           cubic-bezier(0, 0, 0.2, 1)       — elements arriving
--ease-spring        cubic-bezier(0.34, 1.56, 0.64, 1) — subtle bounce (chips, buttons)
```

**Specific animations:**
- Sidebar collapse/expand: `width` transition `--duration-slow` `--ease-out`
- Chat message enter: slide up 8px + fade in, `--duration-slow` `--ease-out`, staggered 50ms between messages on load
- Loading dots (typing indicator): three dots scale pulse, 400ms interval, staggered 133ms
- Follow-up chips: scale from 0.95 + fade in, `--duration-normal` `--ease-spring`
- Modal enter: scale from 0.97 + fade in, `--duration-slow` `--ease-out`
- SSE stream states (thinking → interpreting → executing): crossfade the status text, `--duration-normal`

**What to avoid:**
- No spinning loaders except the send button while a query is in progress
- No bouncing or elastic effects on data-displaying components (tables, charts)
- No animation on the result table rows — it would look chaotic with 100 rows

---

## 8. Iconography

Use `lucide-react` exclusively. No other icon libraries.

Key icons and their usage in FloatChat:
- `Waves` — FloatChat wordmark accent, water-related actions
- `MessageCircle` — new conversation
- `Send` — submit query button
- `Download` — export chart (PNG/SVG)
- `ChevronDown` / `ChevronRight` — collapsible sections (SQL block)
- `Plus` — create new session
- `Trash2` — delete session
- `Pencil` — rename session
- `Map` — navigate to dashboard / map views
- `BarChart2` — charts / visualization
- `Search` — search/filter
- `X` — close / cancel / clear
- `Check` — confirm / success
- `AlertCircle` — error states
- `Info` — informational tooltips
- `Loader2` — spinner (animated with `animate-spin`)
- `LogIn` / `LogOut` — authentication actions
- `User` — user profile / account

Icon sizes: `16px` for inline/text-adjacent, `20px` for button icons, `24px` for navigation, `32px` for empty state illustrations.

---

## 9. Authentication Pages Design

### 9.1 Login Page (`/login`)
Layout: centered card on the full-page background. The background illustration is slightly more visible here (wave opacity at 25–30% in light mode, wave silhouette more prominent in dark mode) since there is no sidebar or content competing with it.

Card: `--color-bg-elevated`, `--radius-2xl`, `--shadow-lg`, max-width 420px, centered vertically and horizontally.

Card content top-to-bottom:
1. FloatChat wordmark (`Fraunces`, `--text-3xl`) with `Waves` icon
2. Tagline: "Ocean data, in plain English." — `DM Sans` `--text-sm` `--color-text-muted`
3. Gap
4. Email input
5. Password input
6. "Sign in" primary button (full width)
7. "Forgot password?" ghost text link
8. Divider with "or"
9. "Create an account" secondary button (full width)

No social login (Google, GitHub) in v1.

### 9.2 Signup Page (`/signup`)
Same layout as login. Card content:
1. Wordmark + tagline
2. Name input
3. Email input
4. Password input
5. "Create account" primary button (full width)
6. "Already have an account? Sign in" ghost text link

### 9.3 Auth Page Rules
- Background illustration is the only decoration on auth pages — no sidebar, no nav
- Error messages appear as inline text below the relevant input in `--color-danger`, `--text-sm`
- Success state (after signup email sent): replace the form with a confirmation message in the same card
- Loading state on submit: disable form, show `Loader2` spinner in the button

---

## 10. Dark Mode Implementation

Use Tailwind CSS's `class` strategy for dark mode (not `media` — this allows user-controlled toggle).

Add `class="dark"` to the `<html>` element when dark mode is active. Store the user's preference in `localStorage` under key `floatchat-theme`. Default to the user's OS preference (`prefers-color-scheme`) on first visit.

Add a theme toggle button in the sidebar footer (sun/moon icon, `lucide-react`'s `Sun` and `Moon`). On click, toggle the `dark` class on `<html>` and persist to `localStorage`.

The Tailwind config must define all CSS variables under `:root` for light mode and `.dark` for dark mode. All components use the semantic token names — never hardcode hex values in component files.

---

## 11. Tailwind Configuration Notes

The `tailwind.config.ts` must be set up before any component is written. Key configuration requirements:

- `darkMode: 'class'`
- Extend `colors` with all semantic token names mapped to their CSS variable (`ocean-primary: 'var(--color-ocean-primary)'` etc.)
- Extend `fontFamily` with `display`, `body`, and `mono` mapped to the three font stacks
- Extend `borderRadius` with all custom radius tokens
- Extend `boxShadow` with all shadow tokens
- Extend `transitionDuration` and `transitionTimingFunction` with animation tokens
- Add Google Fonts import for `Fraunces`, `DM Sans`, and `JetBrains Mono` in `layout.tsx`

---

## 12. shadcn/ui Theme Configuration

When running `npx shadcn-ui@latest init`, configure:
- Style: `default`
- Base color: `slate` (closest to the ocean palette — will be overridden by custom tokens)
- CSS variables: `yes`

After init, replace the generated CSS variable values in `globals.css` with the FloatChat token values from §2. The shadcn components will automatically use the correct colors through their CSS variable references.

Components to install from shadcn: `button`, `input`, `textarea`, `card`, `dialog`, `dropdown-menu`, `popover`, `tooltip`, `badge`, `separator`, `avatar`, `scroll-area`, `tabs`.

---

## 13. Accessibility Requirements

- All color combinations must meet WCAG AA contrast ratio (4.5:1 for text, 3:1 for UI components)
- `--color-ocean-primary` on `--color-bg-base` in light mode: verified at 4.8:1 — passes AA
- `--color-text-primary` on `--color-bg-surface` in both modes: verified at 9:1+ — passes AAA
- Focus rings must be visible in both modes — 2px offset ring in `--color-ocean-light`
- Never rely on color alone to convey meaning — always pair with text or icon
- All interactive elements minimum touch target: 44×44px

---

## 14. Responsive Breakpoints

Follow Tailwind defaults:
```
sm:   640px    — large phones, small tablets
md:   768px    — tablets, sidebar collapses below this
lg:   1024px   — laptops, full sidebar visible
xl:   1280px   — large screens
2xl:  1536px   — wide monitors
```

Mobile-specific rules:
- Below `md`: sidebar collapses to hamburger icon, full-width chat thread
- Below `sm`: result tables switch to horizontal scroll, charts minimum 300px height
- Touch targets minimum 44px throughout
