---
title: RegKnots User Guide
subtitle: Maritime Compliance Co-Pilot
date: 2026-05-11
---

# RegKnots User Guide

*Maritime Compliance Co-Pilot for U.S. Commercial Vessel Operators*

**Version 1.0  ·  May 2026**

---

## Welcome

RegKnots is a regulatory copilot built by mariners, for mariners. It is designed to help you find, understand, and apply U.S. federal maritime regulations (CFR Titles 33, 46, 49), international conventions (SOLAS, MARPOL, STCW, IMDG, ISM), and related guidance — and to do so quickly enough to be useful on the bridge, in the engine room, or alongside.

This guide walks through what RegKnots is, how to use it, and where its limits are. Read it once, then keep it nearby. If you spot something it doesn't cover, write us — every revision of this guide is shaped by what our users actually ask.

This guide is structured for cover-to-cover reading on a print-out at the chart table, but each section stands alone if you only need a refresher on one feature.

### What RegKnots Is

- A search-and-synthesis tool that retrieves the relevant regulatory text for your question, then explains it in plain language with citations you can verify.
- A vessel-aware assistant that tailors answers to your specific operation: vessel type, flag state, route, cargo, certifications.
- A study aid for cadets and instructors preparing for USCG exams — with quizzes and study guides generated from real CFR / STCW / SOLAS material.
- A practical reference for the workflows around regulations: PSC inspections, drills, log entries, port-state preparation, and crew documentation.

### What RegKnots Is Not

- **Not legal advice.** RegKnots is a navigation aid. Compliance decisions remain the responsibility of the licensed mariner, the company, and counsel.
- **Not a substitute for the source documents.** Every cited regulation links to the controlling text. Use the citations; do not rely on the paraphrase alone for compliance-critical decisions.
- **Not a casual-conversation assistant.** Off-topic questions are politely declined. RegKnots is intentionally scoped to maritime compliance.

---

## Quick Start

Five minutes from sign-up to first useful answer.

### 1. Create your account

Visit **regknots.com** and click **Get Access**. Provide an email, a password, and your maritime role (Mariner / Cadet & Student / Teacher & Instructor / Shore-Side Compliance / Legal Consultant). This determines what features RegKnots emphasizes for you.

You'll receive a verification email. Confirm it before reaching the 5-message soft cap.

### 2. Set up your vessel profile

After signing in, you'll be prompted to add a vessel. The vessel profile is the single most important context RegKnots uses to scope answers. Provide:

- **Vessel name**
- **Vessel type** (containership, towing vessel, passenger, fishing, etc.)
- **Flag state**
- **Route types** (international, near-coastal, inland, etc.)
- **Gross tonnage**
- **Subchapter** (e.g., Subchapter M for towing)
- **Inspection certificate type** (COI, MSMC, etc.)
- **Manning requirement** (if known)

You can add more vessels later from the **Vessel** menu. RegKnots will use whichever vessel is active when you ask a question. You can switch active vessels from the vessel pill above the input bar.

### 3. Ask your first question

A good first question to test the system:

> What are the inspection requirements for fire extinguishers on my vessel?

You should see an answer that references your specific vessel context (vessel type, flag, subchapter) and cites the controlling CFR / SOLAS / class society sections. The citations are clickable for verification.

### 4. Read the answer carefully

Look for three things at the top of every answer:

1. **The plain-language synthesis** — what the regulation says, explained in mariner-speak.
2. **The citations** — the amber chips at the bottom of the response. Each is a real, verifiable section.
3. **The disclaimer** — *"Navigation aid only — not legal advice."* Always present in the footer.

---

## Asking Questions

### Questions that work well

- **Specific regulatory questions.** *"How often must a Subchapter M towing vessel test its bilge alarm?"*
- **Workflow / procedure questions.** *"What goes in the Oil Record Book when I switch from bunker tank A to tank B?"*
- **Comparison questions.** *"What's the difference between a Type I and Type V PFD?"*
- **Applicability questions.** *"Does 46 CFR Subchapter D apply to my barge?"*
- **Pre-inspection prep.** *"What will a USCG inspector look for during my annual COI inspection?"*
- **Document and log questions.** *"What entries does the GMDSS radio log need?"*

### Questions that work less well (today)

- **Pricing and procurement questions.** RegKnots is a regulatory tool, not a vendor guide. Ask the regulator, not us, what an approved item costs.
- **Time-sensitive / breaking-news questions.** *"What did the USCG announce yesterday?"* RegKnots' corpus is refreshed regularly but not in real time. For breaking guidance, check the Marine Safety Information Bulletin feed.
- **Personal career advice.** RegKnots will politely decline. It is scoped to compliance.
- **Vessel-specific operational decisions.** *"Should I sail through this weather?"* The captain decides; RegKnots is not in that loop.

### Why vessel context matters

Maritime regulations apply differently across vessel types, flag states, routes, and certificates of inspection. A single CFR section may have one rule for a 200-GT inspected passenger vessel and a different rule for an uninspected fishing vessel. RegKnots uses your vessel profile to filter and weight regulations so the answer is scoped to your specific operation.

The vessel pill above the input bar shows which vessel is active. If it says *"No vessel"* and you're asking a vessel-specific question, the answer will be more general than it could be. Switch vessels mid-conversation by tapping the pill.

### Voice input

The microphone icon to the left of the message box transcribes spoken questions via your device's speech recognition. Useful when you're standing at a console with greasy hands or wearing gloves. Tap once to start, again to stop. The transcribed text appears in the input box; review and edit before sending.

### Verbosity: Brief, Standard, Detailed

The **Verbosity** control (top of the chat surface) adjusts answer length and format. The default is "Standard," which we tuned for most maritime questions.

- **Brief** — concise; lead citation + a one-paragraph answer. Useful on a phone during an inspection.
- **Standard** — current default. Multi-paragraph, multiple citations, applicability noted.
- **Detailed** — sectioned, thorough, often includes applicability tables and edge-case notes. Good for cadets studying for exams or chief mates writing a procedure.

Verbosity can be overridden for a single message (the dropdown next to the vessel pill). Your saved default lives in **Account → Verbosity**.

### Following up

After an answer, you can ask a follow-up in the same conversation: *"What about for vessels under 100 GT?"* or *"Cite the part of the regulation that says that."* RegKnots will retrieve against the combined context of your prior question and the new one, so it stays anchored to the topic.

If you want to start fresh on a different topic, tap **New Chat** in the menu instead of asking a follow-up. Mixing topics in a single conversation can blur the retrieval scope.

---

## Understanding the Answer

### Cited regulations (the amber chips)

Every answer that references a regulation includes one or more amber **citation chips** at the bottom of the response. Each chip names the section (e.g., *46 CFR 199.180*). Tap a chip to view the actual regulatory text. If RegKnots cannot verify a section it cited, that chip will not appear — we strip unverifiable citations rather than show them.

If the citation chips don't match what you expected, the most common cause is the vessel profile. A general question with no vessel set will pull broader citations; a vessel-specific question will pull narrower ones.

### Confidence tiers

When you ask a question, RegKnots routes the answer to one of four confidence tiers, shown as a chip at the top of the response:

- **[Verified] RegKnot Verified** (green chip) — the answer is cited to your regulations corpus and the citation has been verified against the source. This is the highest-trust tier.
- **[Industry Standard] Industry Standard** (teal chip with anchor icon) — the answer reflects settled maritime engineering or seamanship knowledge that virtually all competent mariners would agree on. No specific regulation is claimed; an anchor footnote at the bottom of the message makes the epistemic status explicit.
- **[Web Reference] Web Reference** (amber chip with globe icon) — the answer comes from a trusted maritime source on the web, not the regulations corpus. Includes a confidence score (1–5) and a disclaimer that the linked source should be verified.
- **[Best Effort] Best Effort** (slate chip with warning icon) — RegKnots could not locate the answer in the corpus or settled industry knowledge. Treat as a starting point only.

### Web-fallback yellow card

When the corpus doesn't have a complete answer but a trusted external maritime source does, RegKnots may surface a **yellow card** below the main response. The card includes:

- The source URL and domain
- A verbatim quote from the source
- A confidence score (1–5)
- A "verified," "consensus," or "reference" badge depending on the strength of the corroborating evidence

The yellow card is intentionally visually distinct from corpus citations. Treat it as a useful pointer that requires you to click through and verify, not as a RegKnots-vouched answer.

### Why an answer might hedge

If the answer says something like *"the retrieved context does not directly address..."*, it means the corpus contained related material but not the specific answer you asked for. This is honest behavior — RegKnots prefers to admit a gap rather than fabricate. When this happens:

- Check the citation chips — the related material may still be useful context.
- Try rephrasing the question with more specific vessel context or section names.
- Check the yellow web-fallback card if one appeared.
- If the question is settled industry knowledge (not a regulatory specific), look for the Industry Standard tier chip.

---

## Working With Your Conversation

### Stopping a response

Long answers take time — typically 5–15 seconds, occasionally more. If you need to stop a generation in progress (say, you realized you asked the wrong question), tap the red **Stop** button to the right of the input box. It replaces the Send button while a response is generating.

When you stop, the partial answer you've already seen is preserved in the conversation with an amber **Stopped — incomplete** badge. You can then ask a new question without losing context.

### If the connection drops

If your device loses connectivity or backgrounds mid-response, RegKnots will display a teal banner saying *"Hang tight — your answer will appear when you're back online."* The server continues generating, and the answer will appear when the connection recovers.

If the answer doesn't arrive within 30 seconds, you'll see an amber banner with your original question and a **Resend** button. One tap re-submits.

### Conversation history

All your conversations are saved automatically. Access them from the **History** menu. You can:

- **Search** conversations by keyword
- **Rename** a conversation (long-press the title)
- **Archive** old conversations to declutter the list
- **Export** a conversation to PDF or plain text for record-keeping

Conversations are private to your account and are not shared with other RegKnots users. Conversations inside a Wheelhouse workspace are visible to all workspace members.

### Resuming a conversation later

Open a conversation from History and continue asking questions. RegKnots loads the full thread (up to 10 prior messages for context) and treats the next question as a follow-up.

---

## Vessel Profile

The vessel profile is the most important context you give RegKnots. A well-completed profile produces noticeably better answers.

### What we store

- Vessel name, type, and flag
- Gross tonnage and length
- Route types and limitations
- Subchapter (M, T, K, etc.)
- Inspection certificate type
- Manning requirement
- Key equipment (optional)
- Additional details (free-form notes you find useful)

We do **not** store: vessel IMO number, cargo manifests, crew personally identifiable information, or any operational data beyond the regulatory characteristics above.

### Why it improves answers

Maritime regulations are layered. A question about life-saving equipment, for example, may need to consider:

- The vessel's subchapter (M, T, K, etc.)
- Whether the vessel is inspected or uninspected
- The vessel's route (international SOLAS, near-coastal, lakes/bays, etc.)
- The vessel's gross tonnage threshold
- The vessel's certificate of inspection type

Without vessel context, RegKnots returns the most generic answer that covers all possibilities. With vessel context, it scopes the answer to your specific configuration.

### Multiple vessels

You can register multiple vessels under one account. This is useful for:

- Captains who relieve on multiple vessels in a company
- Port engineers who oversee a fleet
- Cadets who want to compare regulatory regimes across vessel types

Switch active vessels via the vessel pill above the input bar. Each conversation is anchored to the vessel that was active when the conversation started; switching mid-conversation updates the vessel for future turns.

### Document upload (Captain tier)

You can upload your COI, CSC plate, or certificate documents. RegKnots extracts the relevant regulatory characteristics (subchapter, route limitations, manning, etc.) and populates the vessel profile. Always review the extracted data before confirming — OCR accuracy varies, and a misread subchapter changes the answers RegKnots gives you.

---

## Study Tools (Cadets & Instructors)

If your role is **Cadet & Student** or **Teacher & Instructor**, the Study Tools surface is automatically enabled. Access it from **Quizzes & Guides** in the menu.

### Quiz generator

Ask the quiz generator for a quiz on a topic or regulation, and it will produce a multiple-choice quiz with answer keys and citations. Examples:

- *"Generate a 10-question quiz on 33 CFR Subchapter O (Pollution)."*
- *"Quiz me on the National Maritime Center exam-bank topics for OICEW."*

Take the quiz directly in RegKnots. Your answers are auto-graded against the citation-verified answer key. Wrong answers include the controlling citation so you can read the source.

### Study guides

Ask for a study guide on a topic; RegKnots produces a structured outline with key regulations, common exam topics, and citation-anchored explanations. Useful for:

- USCG license exams (Master, Mate, Engineer, AB, OS, etc.)
- STCW certification preparation
- Class society audits
- Pre-inspection prep

### Citation verification

Every quiz answer and study guide section is verified against the regulations corpus before display. If RegKnots cannot verify a citation, it strips it rather than show an unverifiable reference.

### Toggling Study Tools

If you don't need Study Tools, hide them from the menu via **Account → Study Tools → Off**. The feature is available on all subscription tiers.

---

## Account Settings

### Persona

Your maritime role, set at sign-up. Determines whether Study Tools is enabled by default and influences the prompt style. Change anytime in **Account → Persona**.

### Jurisdiction focus

Optional. Tells RegKnots which jurisdiction's regulations to emphasize when more than one applies: **United States**, **United Kingdom**, **Australia**, **Singapore**, **Hong Kong**, **Norway**, **Liberia**, **Marshall Islands**, **Bahamas**, or **International / Mixed**.

If your operation crosses jurisdictions, leave this on **International / Mixed** and let the vessel profile do the scoping.

### Verbosity preference

Your default verbosity (**Brief**, **Standard**, or **Detailed**). The per-message dropdown overrides it for a single turn.

### Email notifications

Configure which alerts you receive (certificate expiry reminders, regulation updates, etc.) in **Account → Notifications**.

### Subscription

Manage your plan, billing, and payment method in **Account → Subscription**. Tier-specific limits:

- **Free trial** — 50 messages, then upgrade required
- **Mate** — 100 messages per month
- **Captain** — unlimited
- **Wheelhouse** — multi-seat for crews and fleets

---

## Giving Back

RegKnots gives **10% of every dollar of revenue** (not profit, revenue) to organizations doing real work in maritime communities and beyond. The current beneficiaries are:

- **Mercy Ships** — civilian hospital ships providing free medical care worldwide
- **Waves of Impact** — surf therapy and ocean-based programs for children facing exceptional challenges
- **Elijah Rising** — anti-trafficking work in Houston and the Port of Houston region
- **Women Offshore** — community, mentorship, and scholarships for women working on, above, and below the water

You can read more about each organization, suggest a new one, and see the donation accounting at **regknots.com/giving**.

---

## Support

If RegKnots gets something wrong, misses a regulation you care about, or behaves unexpectedly, please tell us. We log every report and route it to engineering directly.

- **Email**: hello@regknots.com
- **In-app**: **Help & Support** menu → Submit a Question
- **For corpus gaps**: ask the question normally; if RegKnots can't find it, the system automatically flags the gap for us to ingest.

We typically respond within one business day. For urgent compliance questions, use the controlling regulation directly — RegKnots is a navigation aid, not an emergency line.

---

## Disclaimer

RegKnots is a navigation aid for licensed mariners, compliance professionals, and maritime students. It is not legal advice. RegKnots does not certify compliance, replace the controlling regulatory text, or substitute for advice from qualified counsel.

Every cited regulation links to a verifiable source. For any compliance-critical decision, read the source. The licensed mariner, the operating company, and counsel remain responsible for compliance determinations.

By using RegKnots, you accept that the service is provided "as-is," without warranty of any kind, and that the operator (RegKnots LLC) is not liable for compliance failures, regulatory enforcement actions, or operational decisions made on the basis of RegKnots output.

For the complete terms, see **regknots.com/terms**. For our privacy posture, see **regknots.com/privacy**.

---

*Last revised: May 11, 2026 (RegKnots v1.0)*

*Built by mariners, for mariners. — Karynn & Blake Marchal*
