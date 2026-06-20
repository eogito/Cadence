# Welcome & Help Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single "How Cadence works" overlay modal that auto-opens once for new users (welcome moment) and is reopenable anytime via a **?** button (persistent help).

**Architecture:** Pure frontend in `src/static/index.html`. One overlay element (`#helpOverlay` + `#helpCard`) styled with the existing Hand-Drawn CSS variables. `showHelp()`/`closeHelp()` toggle an `.open` class; the **?** nav button, a first-run check in `checkAuth()` (gated by `localStorage['cadence_welcome_seen']`), backdrop click, and Esc all wire into it. No backend, DB, routes, or dependencies.

**Tech Stack:** Vanilla HTML/CSS/JS (single static page). No JS test runner exists, so verification is structural (Grep) plus manual.

Spec: `docs/superpowers/specs/2026-06-20-welcome-help-design.md`.

---

## File Structure

- **Modify only:** `src/static/index.html`
  - CSS block (near the `#moreMenu` rules, ~line 271): add overlay/card styles.
  - `<nav>` (~line 301): add the **?** Help button.
  - After `</header>` (~line 304): add the `#helpOverlay` modal markup + content.
  - JS (after `fmtTime`, ~line 599 area) : add `showHelp`/`closeHelp` + Esc listener.
  - `checkAuth()` (~line 590, right after `calInit();`): add the first-run auto-open.

---

## Task 1: Modal styles + content markup

**Files:**
- Modify: `src/static/index.html` (CSS near line 271; markup after `</header>` line 304)

- [ ] **Step 1: Add the overlay/card CSS**

Find this block (around line 271):

```css
    #moreMenu.hidden { display: none; }
```

Insert immediately AFTER it:

```css
    #helpOverlay { position: fixed; inset: 0; background: rgba(45,45,45,.45); z-index: 1000;
      display: none; align-items: flex-start; justify-content: center; overflow-y: auto; padding: 40px 16px; }
    #helpOverlay.open { display: flex; }
    #helpCard { background: var(--paper); border: 2px solid var(--pencil); border-radius: var(--wobbly-md);
      box-shadow: var(--shadow-hard); max-width: 640px; width: 100%; padding: 28px 26px 32px; position: relative; }
    #helpCard h2 { font-family: var(--font-head); margin: 0 0 2px; font-size: 1.7rem; }
    #helpCard .help-section { margin-top: 18px; }
    #helpCard .help-section h3 { font-family: var(--font-head); font-size: 1.08rem; margin: 0 0 4px; }
    #helpCard .help-section p { margin: 0; font-size: .92rem; line-height: 1.55; }
    #helpCard .help-faq { margin-top: 6px; }
    #helpCard .help-faq strong { display: block; margin-top: 12px; font-family: var(--font-head); }
    #helpClose { position: absolute; top: 10px; right: 14px; background: none; border: none;
      font-size: 1.8rem; line-height: 1; cursor: pointer; color: var(--pencil); }
```

- [ ] **Step 2: Add the modal markup**

Find the end of the header (around line 304):

```html
</header>
```

Insert immediately AFTER it:

```html
<div id="helpOverlay" onclick="if(event.target===this)closeHelp()">
  <div id="helpCard">
    <button id="helpClose" type="button" onclick="closeHelp()" aria-label="Close">&times;</button>
    <h2>Welcome to Cadence</h2>
    <p class="subtitle">Your inbox, turned into a calendar — and nothing touches your calendar without your approval.</p>

    <div class="help-section">
      <h3>The calendar is home</h3>
      <p>Each day shows dots for its events and tasks. Click any day to see that day's schedule and a breakdown of its email.</p>
    </div>

    <div class="help-section">
      <h3>Today's two powers</h3>
      <p><strong>Process today's emails</strong> reads today's unread mail, sorts out the noise, and shows you the actionable ones as proposed tasks and events — you pick which to schedule. <strong>Plan my day</strong> builds a schedule from your day's events, tasks, and intent, then lets you push timed blocks straight into Outlook.</p>
    </div>

    <div class="help-section">
      <h3>The "More" menu</h3>
      <p>Up top, <strong>More</strong> holds Meeting Prep, Tasks, Contacts, and My Rules (personal context, recurring reminders, and which inbox sections to track).</p>
    </div>

    <div class="help-section">
      <h3>Your privacy</h3>
      <p>You sign in with Microsoft. Cadence reads your Outlook mail and calendar to do its work; your sign-in tokens are encrypted at rest, and every change to your calendar happens only after you approve it.</p>
    </div>

    <div class="help-section help-faq">
      <h3>FAQ</h3>
      <strong>Why Microsoft only?</strong>
      <p>Microsoft's bar for serving mail access publicly is much lighter than Gmail's, so the public app uses Outlook. (A Gmail version exists on a separate branch.)</p>
      <strong>Does it auto-create events?</strong>
      <p>No. Cadence only ever proposes — you approve before anything lands on your calendar.</p>
      <strong>How do I choose which inbox sections to track?</strong>
      <p>Open <strong>More → My Rules</strong> and pick Focused, Other, or both.</p>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Structural verification**

Run:
```bash
cd "C:/Users/Glen Lin/ai-task-scheduler"
grep -c 'id="helpOverlay"' src/static/index.html
grep -c 'id="helpCard"' src/static/index.html
grep -c '#helpOverlay.open' src/static/index.html
```
Expected: `1` for each.

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat: welcome & help modal markup + styles"
```

---

## Task 2: Wiring — ? button, open/close, Esc, first-run

**Files:**
- Modify: `src/static/index.html` (nav ~line 301; JS after `fmtTime` ~line 599; `checkAuth` ~line 590)

- [ ] **Step 1: Add the ? Help button to the nav**

Find this in the `<nav>` (around line 301 — the close of the relative span wrapping the More menu), then the authArea span:

```html
    </span>
    <span id="authArea" style="margin-left:16px;font-size:.8rem;display:flex;align-items:center"></span>
```

Replace with (insert the Help button between them):

```html
    </span>
    <button type="button" id="helpBtn" onclick="showHelp()" title="How Cadence works" style="margin-left:8px">? Help</button>
    <span id="authArea" style="margin-left:16px;font-size:.8rem;display:flex;align-items:center"></span>
```

- [ ] **Step 2: Add showHelp/closeHelp + Esc handler**

Find the `fmtTime` function (around line 601) and insert this BEFORE it:

```javascript
  function showHelp() { document.getElementById('helpOverlay').classList.add('open'); }
  function closeHelp() { document.getElementById('helpOverlay').classList.remove('open'); }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeHelp(); });

```

- [ ] **Step 3: Add the first-run auto-open to checkAuth**

Find this inside `checkAuth()` (around line 590):

```javascript
        main.style.display = '';
        splash.style.display = 'none';
        calInit();
```

Replace with:

```javascript
        main.style.display = '';
        splash.style.display = 'none';
        calInit();
        if (!localStorage.getItem('cadence_welcome_seen')) {
          showHelp();
          localStorage.setItem('cadence_welcome_seen', '1');
        }
```

- [ ] **Step 4: Structural verification**

Run:
```bash
cd "C:/Users/Glen Lin/ai-task-scheduler"
grep -c 'id="helpBtn"' src/static/index.html          # 1
grep -c 'function showHelp(' src/static/index.html     # 1
grep -c 'function closeHelp(' src/static/index.html    # 1
grep -c 'cadence_welcome_seen' src/static/index.html   # 2
```
Expected counts shown in the comments.

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat: wire ? Help button, open/close, Esc, first-run auto-open"
```

---

## Final verification

- [ ] **App still imports** (serves the static file unchanged structurally):

```bash
cd "C:/Users/Glen Lin/ai-task-scheduler"
./venv/Scripts/python.exe -c "import src.main; print('ok')"
```
Expected: `ok`.

- [ ] **Manual** (start server `./venv/Scripts/python.exe -m uvicorn src.main:app --reload`, sign in):
  - In browser devtools console run `localStorage.removeItem('cadence_welcome_seen')`, then reload → the help modal auto-opens once.
  - Close it (× / backdrop click / Esc) → reload → it does NOT re-open.
  - Click **? Help** in the nav → modal opens again.
  - Content reads correctly and matches the Hand-Drawn styling.
