# Founders Portal — UI/UX Design Skill
## Design Intelligence for Internal Insurance Agency Tools
*Tailored for: Flask + Vanilla HTML/CSS/JS · Internal B2B Dashboard · 8 non-technical users*

---

## 1. Design Philosophy

This is an **internal operations tool**, not a marketing site. Every design decision should optimize for:

- **Clarity over beauty** — agents need to understand data at a glance, not be impressed
- **Low cognitive load** — tech-illiterate users must never feel confused or overwhelmed
- **Actionability** — every page should make it obvious what the user needs to do next
- **Trust** — the UI must feel professional and reliable, not like a side project
- **Speed** — pages should feel instant, no unnecessary animations or loading states

**Style classification:** Enterprise Dashboard · Soft UI Evolution · Minimal & Direct  
**Never use:** Glassmorphism, Brutalism, Cyberpunk, Y2K, heavy animations, dark mode (agents use this during business hours on standard monitors)

---

## 2. Color System

### Primary Palette
```
Navy (primary brand):     #1B2A4A   — headers, sidebar, primary actions
Blue (interactive):       #185FA5   — links, active states, info badges
Gold (accent):            #C9A84C   — highlights, warnings, brand moments
White (surface):          #FFFFFF   — card backgrounds, main content areas
Light Gray (background):  #F4F6F9   — page background, secondary surfaces
Mid Gray (borders):       #E2E6ED   — dividers, input borders, table lines
Dark Gray (body text):    #4A5568   — secondary text, labels, captions
```

### Semantic Colors (status indicators)
```
Success / Active:    #2D6A4F bg · #EAF3DE fill   — active policies, verified, matched
Warning / Upcoming:  #854F0B bg · #FAEEDA fill   — 30-60 day terms, attention needed  
Danger / Urgent:     #A32D2D bg · #FCEBEB fill   — <30 day terms, unmatched, errors
Info / New:          #185FA5 bg · #E6F1FB fill   — new enrollments, informational
Neutral / Inactive:  #5F5E5A bg · #F1EFE8 fill   — termed, historical, disabled
```

### Urgency Color Coding (used consistently across all tables)
```
🔴 Red    (#FCEBEB)  — under 30 days / critical / unmatched
🟠 Orange (#FCECD)   — 30-60 days / warning / needs attention  
🟡 Yellow (#FFF2CC)  — 60-90 days / watch / informational
🟢 Green  (#D9EAD3)  — no issues / verified / in sync
```

**Rule:** Use this exact color system everywhere urgency is communicated. Never invent new status colors.

---

## 3. Typography

### Font Stack
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
```
Use the system font stack — no Google Fonts import needed, loads instantly, looks native on every OS.

### Type Scale
```
Page title:      22px / weight 500 / color #1B2A4A
Section header:  17px / weight 500 / color #1B2A4A
Card title:      15px / weight 500 / color #1B2A4A
Table header:    11px / weight 500 / color #4A5568 / uppercase / letter-spacing 0.06em
Body text:       14px / weight 400 / color #4A5568 / line-height 1.6
Small/label:     12px / weight 400 / color #4A5568
Micro/caption:   11px / weight 400 / color #888888
Data values:     14px / weight 500 / color #1B2A4A  (numbers in tables)
Large metric:    24px / weight 500 / color #1B2A4A  (metric cards)
```

### Rules
- **Two weights only:** 400 (regular) and 500 (medium). Never 600 or 700 — too heavy for dashboard context.
- **Sentence case always** — never ALL CAPS for content, never Title Case for body text
- Table headers are the one exception — use uppercase + letter-spacing for column labels
- Monospace font (`font-family: 'Courier New', monospace`) for MBI numbers, IDs, codes only

---

## 4. Layout & Spacing

### Page Structure
```
┌─────────────────────────────────────────────────┐
│  SIDEBAR (200px fixed)  │  MAIN CONTENT (flex 1) │
│  ─────────────────────  │  ─────────────────────  │
│  Logo + agency name     │  Top bar (title + CTA)  │
│  Navigation sections    │  Metric cards (4-col)   │
│  Nav items w/ dots      │  Content sections       │
│  ─────────────────────  │                         │
│  Agent name + avatar    │                         │
└─────────────────────────────────────────────────┘
```

### Spacing Scale
```
4px   — micro gaps (between icon and label)
8px   — small gaps (between related items)
12px  — component internal padding
16px  — card padding, section gaps
20px  — page padding
24px  — section separation
32px  — major section breaks
```

### Grid Rules
- Metric cards: always 4-column grid on desktop, 2-column on tablet, 1-column on mobile
- Two-column sections: use `grid-template-columns: minmax(0,1fr) minmax(0,1fr)` — never `1fr 1fr` alone
- Always use `gap` not margins between grid items
- Content max-width: none for full-width dashboards — let it fill

---

## 5. Components

### Sidebar Navigation
```css
/* Sidebar */
width: 200px;
background: #FFFFFF;
border-right: 0.5px solid #E2E6ED;

/* Nav section labels */
font-size: 10px;
color: #888888;
text-transform: uppercase;
letter-spacing: 0.06em;
padding: 12px 8px 4px;

/* Nav items */
display: flex;
align-items: center;
gap: 8px;
padding: 7px 12px;
font-size: 13px;
border-radius: 8px;
margin: 1px 4px;

/* Active state */
background: #E6F1FB;
color: #185FA5;
font-weight: 500;

/* Color dots — each section gets a color */
width: 7px; height: 7px; border-radius: 50%;
```

Color dot assignments:
- My Book section → Blue `#378ADD`
- Commissions → Green `#639922`
- Tools → Purple `#7F77DD`
- Alerts/Issues → Red `#E24B4A`

### Metric Cards
```css
background: #F4F6F9;    /* secondary surface, no border */
border-radius: 8px;
padding: 12px 14px;

/* Label */
font-size: 11px;
color: #4A5568;
margin-bottom: 6px;

/* Value */
font-size: 22px;
font-weight: 500;
color: #1B2A4A;

/* Sub-text */
font-size: 11px;
color: #4A5568;  /* default */
color: #3B6D11;  /* positive trend */
color: #A32D2D;  /* negative / needs attention */
```

### Cards / Sections
```css
background: #FFFFFF;
border: 0.5px solid #E2E6ED;
border-radius: 12px;
overflow: hidden;

/* Section header inside card */
display: flex;
align-items: center;
justify-content: space-between;
padding: 12px 16px;
border-bottom: 0.5px solid #E2E6ED;
```

### Tables
```css
width: 100%;
border-collapse: collapse;
font-size: 12px;

/* Headers */
th {
  font-size: 11px;
  font-weight: 500;
  color: #4A5568;
  text-align: left;
  padding: 8px 16px;
  border-bottom: 0.5px solid #E2E6ED;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* Cells */
td {
  padding: 9px 16px;
  border-bottom: 0.5px solid #E2E6ED;
  color: #1B2A4A;
  vertical-align: middle;
}

/* Last row — no border */
tr:last-child td { border-bottom: none; }

/* Hover */
tr:hover td { background: #F4F6F9; }
```

### Badges / Pills
```css
/* Base */
font-size: 11px;
font-weight: 500;
padding: 2px 8px;
border-radius: 99px;

/* Variants */
.badge-red    { background: #FCEBEB; color: #A32D2D; }
.badge-amber  { background: #FAEEDA; color: #854F0B; }
.badge-yellow { background: #FFF2CC; color: #633806; }
.badge-green  { background: #EAF3DE; color: #3B6D11; }
.badge-blue   { background: #E6F1FB; color: #185FA5; }
.badge-gray   { background: #F4F6F9; color: #4A5568; }
.badge-navy   { background: #1B2A4A; color: #FFFFFF; }
```

### Buttons
```css
/* Primary */
background: #185FA5;
color: #FFFFFF;
border: none;
border-radius: 8px;
padding: 8px 16px;
font-size: 13px;
font-weight: 500;
cursor: pointer;

/* Secondary */
background: #FFFFFF;
color: #1B2A4A;
border: 0.5px solid #E2E6ED;
border-radius: 8px;
padding: 8px 16px;

/* Danger */
background: #FCEBEB;
color: #A32D2D;
border: 0.5px solid #F09595;

/* Hover: darken background 8%, add subtle scale(0.98) on active */
```

### Avatar / Initials Circle
```css
width: 32px; height: 32px;
border-radius: 50%;
background: #B5D4F4;
display: flex;
align-items: center;
justify-content: center;
font-size: 12px;
font-weight: 500;
color: #185FA5;
```

### Section Headers (colored banner style)
```css
background: #1B2A4A;
color: #FFFFFF;
padding: 8px 16px;
font-size: 12px;
font-weight: 500;
text-transform: uppercase;
letter-spacing: 0.06em;
border-radius: 8px;
```

---

## 6. Page Templates

### Agent Dashboard Page
```
Top bar: Page title (left) + "Run Weekly Audit" button (right)
Sub: "Last audit: [date] · Week [N]"

Row 1: 4 metric cards
  [Active Policies] [Unmatched in Zoho] [Upcoming Terms 90d] [Est. Monthly Commission]

Row 2: 2-col grid
  Left:  "Policies by carrier" — horizontal bar chart rows
  Right: "Commission audit" — table with gross/split/amount/status

Row 3: Full width
  "Upcoming terminations" — sortable table, color coded rows

Row 4: Full width  
  "Unmatched policies" — table with reason column
```

### Commission Audit Page
```
Header: Month selector dropdown + "Upload files" button

Summary cards: Total gross · Your 55% · Verified · Discrepancies

Per-carrier breakdown table:
  Carrier | Gross | Line items | Split % | Expected | AJ Paid | Status | Diff

Detail section: expandable per-carrier line item table
  Member name | Action | Amount | Date | Notes
```

### Upcoming Terms Page
```
Filter bar: All / <30 days / 30-60 / 60-90 + Carrier dropdown

Table: Member | DOB | Phone | Carrier | Plan | Eff Date | Term Date | Days | Reason
Color code entire row by urgency tier
```

### Birthday Labels Page
```
Month picker: Jan–Dec buttons (current month highlighted)
Member count: "23 customers with birthdays in April"
Preview: First 5 names listed
Generate button: "Download Avery 5160 CSV"
```

---

## 7. Admin vs Agent Views

### Agent view (default)
- Sees only their own policies, commissions, terms, labels
- No ability to see other agents' data
- Simple, minimal navigation
- Cannot upload files — read only

### Admin view (AJ + Tim)
- Additional "Agency Overview" section in sidebar
- All-agents summary at top of dashboard
- File upload interface for carrier BOB files
- Per-agent breakdown tables
- Commission distribution across all agents
- Flag: `{% if current_user.is_admin %}` in templates

---

## 8. Forms & Inputs

```css
/* Text inputs */
height: 36px;
padding: 0 12px;
border: 0.5px solid #E2E6ED;
border-radius: 8px;
font-size: 14px;
color: #1B2A4A;
background: #FFFFFF;
width: 100%;

/* Focus state */
outline: none;
border-color: #185FA5;
box-shadow: 0 0 0 3px rgba(24, 95, 165, 0.1);

/* Select dropdowns — same styles as text inputs */

/* File upload zone */
border: 2px dashed #E2E6ED;
border-radius: 12px;
padding: 32px;
text-align: center;
background: #F4F6F9;
cursor: pointer;
/* On hover: border-color: #185FA5; background: #E6F1FB; */
```

---

## 9. Responsive Breakpoints

```css
/* Mobile first approach */
/* Default: mobile (< 768px) — single column, stacked nav */

@media (min-width: 768px) {
  /* Tablet — 2-col metric grid, sidebar collapses to icons */
}

@media (min-width: 1024px) {
  /* Desktop — full sidebar, 4-col metric grid, 2-col sections */
}

@media (min-width: 1440px) {
  /* Large desktop — comfortable padding, max readable width */
}
```

Agents primarily use this on desktop during work hours. Mobile support is secondary but should not be broken.

---

## 10. Anti-Patterns — Never Do These

### Visual
- ❌ Gradients on backgrounds (flat colors only)
- ❌ Drop shadows on cards (use borders instead)
- ❌ Dark mode (not appropriate for this tool)
- ❌ Animations longer than 200ms
- ❌ Parallax, scroll effects, or transitions on page load
- ❌ Emoji as icons (use simple CSS shapes or inline SVG)
- ❌ More than 2 font weights
- ❌ Colored backgrounds on the main content area
- ❌ Rounded corners on single-sided borders
- ❌ Tables wider than their container (use `table-layout: fixed`)

### UX
- ❌ Modal dialogs for non-critical actions
- ❌ Confirmation dialogs for read operations
- ❌ Pagination when simple scroll works
- ❌ Tabs that hide content on load
- ❌ Tooltips as the only way to understand a UI element
- ❌ Placeholder text as labels (always use real labels)
- ❌ Red color for anything that isn't an error or urgent alert
- ❌ Disabling buttons without explaining why

### Code
- ❌ Inline styles for colors — always use CSS classes or variables
- ❌ `!important` declarations
- ❌ Fixed heights on text containers
- ❌ `position: fixed` modals (use in-flow overlays)
- ❌ JavaScript for things CSS can handle

---

## 11. Accessibility Rules

- All interactive elements must have `cursor: pointer`
- Minimum text contrast ratio: 4.5:1 (WCAG AA)
- All form inputs must have associated `<label>` elements
- Focus states must be visible — never `outline: none` without a replacement
- Color alone must never be the only indicator of status (always pair with text or icon)
- Table headers must use `<th>` not `<td>`
- Images must have `alt` attributes

---

## 12. Flask/Jinja Template Conventions

### Template inheritance
```html
<!-- base.html — all pages extend this -->
{% extends "base.html" %}
{% block title %}Page Title{% endblock %}
{% block content %}
  <!-- page content here -->
{% endblock %}
```

### Admin-only sections
```html
{% if current_user.is_admin %}
  <!-- admin only content -->
{% endif %}
```

### Status badge helper
```html
<!-- Use this pattern consistently for status badges -->
<span class="badge badge-{{ policy.urgency_class }}">{{ policy.status }}</span>
```

### Empty states
```html
<!-- Always show a helpful empty state, never a blank table -->
{% if not policies %}
<div class="empty-state">
  <p>No policies found. Run the weekly audit to import carrier data.</p>
</div>
{% endif %}
```

### Flash messages
```html
{% with messages = get_flashed_messages(with_categories=true) %}
  {% for category, message in messages %}
    <div class="alert alert-{{ category }}">{{ message }}</div>
  {% endfor %}
{% endwith %}
```

---

## 13. JavaScript Conventions

- **Vanilla JS only** — no jQuery, no React, no frameworks
- Use `document.querySelector` not `document.getElementById`
- Event listeners via `addEventListener`, never inline `onclick`
- `fetch()` for any AJAX calls, always handle errors
- Format currency: `new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(amount)`
- Format dates: `new Date(dateStr).toLocaleDateString('en-US', {month:'short',day:'numeric',year:'numeric'})`
- Round all displayed numbers — never show raw float math results

---

## 14. Design System Quick Reference Card

| Element | Background | Text | Border |
|---|---|---|---|
| Page bg | `#F4F6F9` | — | — |
| Card | `#FFFFFF` | `#1B2A4A` | `0.5px #E2E6ED` |
| Sidebar | `#FFFFFF` | `#4A5568` | `0.5px #E2E6ED` |
| Metric card | `#F4F6F9` | `#1B2A4A` | none |
| Nav active | `#E6F1FB` | `#185FA5` | none |
| Table header | transparent | `#4A5568` | bottom `0.5px` |
| Section banner | `#1B2A4A` | `#FFFFFF` | none |
| Primary button | `#185FA5` | `#FFFFFF` | none |
| Badge red | `#FCEBEB` | `#A32D2D` | none |
| Badge amber | `#FAEEDA` | `#854F0B` | none |
| Badge green | `#EAF3DE` | `#3B6D11` | none |
| Badge blue | `#E6F1FB` | `#185FA5` | none |

---

*This skill file is tailored for the Founders Insurance Agency Portal — Flask backend, vanilla HTML/CSS/JS frontend, internal use by 8 non-technical insurance agents.*
