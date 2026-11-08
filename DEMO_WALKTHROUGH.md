# PromoBridge — 2-Minute Demo Walkthrough Outline

**Live Streamlit Deployment:** [Launch PromoBridge on Streamlit Community Cloud](https://share.streamlit.io/deploy?repository=jinay-mehta/PromoBridge&branch=main&mainModule=app.py)  
**GitHub Repository:** [jinay-mehta/PromoBridge](https://github.com/jinay-mehta/PromoBridge)

---

### Step-by-Step Walkthrough (2 Minutes)

1. **Problem Framing (15 sec):**
   - A viewer discovers a microdrama on Instagram/TikTok/Facebook, clicks the ad, but arrives at a generic screen or cannot find the promised series in the app.
   - PromoBridge solves this pre-publish: it validates that the promo creative maps to an exact show, episode, and timestamped scene evidence before ad spend is committed.

2. **Catalogue Overview (20 sec):**
   - Navigate to the **Catalogue** tab.
   - Point out the active catalogue: **61 episodes across 4 shows**, including the **actual Kuku screenplay pack for *"I Married a Broken Soldier. He was a Duke"*** (50 episodes, 2,000+ scene/dialogue evidence spans) plus 11 benchmark episodes.
   - Note the in-memory **ZIP upload** feature that lets operators drag and drop entire screenplay pack archives (`.zip`) or individual scripts (`.txt`, `.docx`, `.pdf`, `.json`).

3. **Match a Real Kuku Promo Creative (30 sec):**
   - Switch to the **Match a promo** tab.
   - Enter:
     - **Title shown in ad:** `I Married a Broken Soldier`
     - **Promo dialogue transcript:** `You let me believe I was walking toward my husband!`
   - Click **Find matching show & episode**.
   - Point out the result:
     - **Status:** `VERIFIED` (highlighted green)
     - **Match:** `I Married a Broken Soldier. He was a Duke` — `EP_001`
     - **Evidence span:** `LADY JULIANA: "You let me believe I was walking toward my husband!"`
     - **Timecode:** `[00:57.00 - 01:00.10]` with line references.

4. **Safe Failure & Abstention (20 sec):**
   - Test an unrelated creative:
     - **Transcript:** `A spaceship captain discovers a new planet after the engine fails.`
     - **Result:** Conservative `NO MATCH` with score < 0.10.
   - Test an ambiguous / generic short phrase:
     - **Transcript:** `Why are you walking like that? I am tired. That is all.`
     - **Result:** `NEEDS REVIEW` (correct episode retrieved, but flagged for human check).

5. **Human Review & Manifest Export (20 sec):**
   - Click **✓ Approve mapping**.
   - Scroll down to export:
     - Download **Manifest CSV** (for campaign ops, platform deep-linking, and release teams).
     - Download **Traceability JSON** (full audit record with evidence IDs and score breakdown).

6. **Evaluation & Audit Suite (15 sec):**
   - Open the **Evaluation & export** tab.
   - Click **Run evaluation on current catalogue** to test against the 30-case gold set.
   - Show 100% recall on positive cases and 0% false verified rate on ambiguous/negative cases.

---

> **Operational Note:** A `VERIFIED` result means the creative is provably grounded in verified screenplay dialogue. The prototype runs 100% deterministically without external LLM API dependencies. Missing destination URLs remain `UNKNOWN`; PromoBridge never fabricates links.
