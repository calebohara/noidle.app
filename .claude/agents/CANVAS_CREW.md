# The Canvas Crew — noidle.app Homepage Design Team

Permanent design review team for `public/index.html` and related assets.
Spawn all three in parallel whenever you want a full homepage audit.

---

## Members

| Agent | Role | Voice | Color | Owns |
|-------|------|-------|-------|------|
| **Vera** | Visual Designer | James (warm, fast) | `#22c55e` | CSS vars · typography · color · gradients · animations · og.svg |
| **Axel** | UX & Conversion | James (measured, cool) | `#38bdf8` | JS · taskbar demo · CTAs · section flow · copy clarity |
| **Mira** | Layout, Responsive & A11y | Rachel (precise) | `#a78bfa` | Media queries · semantic HTML · ARIA · reduced-motion · vercel.json |

---

## How to invoke

### Full audit (all three in parallel)
```
Spawn The Canvas Crew — run all three agents against public/index.html and report findings.
```

### Individual agents
```
Ask Vera to audit the color system and typography on the homepage.
Ask Axel to review the CTA hierarchy and interactive demo.
Ask Mira to audit accessibility and responsive layout.
```

---

## Agent files

- `.claude/agents/vera.md` — Visual Designer
- `.claude/agents/axel.md` — UX & Conversion Designer
- `.claude/agents/mira.md` — Layout, Responsive & Accessibility Lead

---

## Shared context (read before invoking)

- Homepage: `public/index.html` (1200+ lines, single file, no build step)
- Deployed at: `https://noidle.app` via Vercel
- Theme: dark Win11 aesthetic, primary green `#22c55e`, fonts: Inter + JetBrains Mono
- Security headers: `vercel.json`
- OG image: `public/og.svg` (1200×630)
- Breakpoints: `max-width: 600px` and `max-width: 720px`
- JS: inline vanilla — live clock, IntersectionObserver scroll-reveal, taskbar demo

---

## Improvement checklist (shared baseline)

All three agents enforce this baseline before domain-specific work:

- [ ] WCAG AA contrast (4.5:1 normal text, 3:1 large text) on every text element
- [ ] `prefers-reduced-motion` respected by ALL animations
- [ ] Keyboard navigation works for all interactive elements
- [ ] No horizontal scroll on 375px viewport
- [ ] `<html lang="en">` and sequential heading hierarchy
- [ ] Open Graph tags complete and og:image is absolute HTTPS URL
