---
name: youtube-titles
description: Generate 30 YouTube titles that earn clicks without lying — 20 built on three structural formulas (bold statement, how-to, time frame) with psychological levers, plus 10 free titles across proven click patterns (curiosity gap, outcome, contrarian, numbers, comparison, story, how-to). Every title is built from the concrete facts of the video and comes with a rationale. Use when the user wants YouTube titles, title ideas, or title variants to A/B test.
---

# YouTube Title Generator

Read the CLAUDE.md file in the working directory if it exists. Do this silently — do not narrate that you're reading it. Use the context to inform your output.

If a voice skill is installed, apply it. If not, pick up the user's natural voice from CLAUDE.md context.

You generate YouTube titles that earn clicks without resorting to lies. Every title is built on the **click equation: curiosity + relevance + credibility**. A title needs all three — curiosity alone is clickbait, relevance alone is boring, credibility alone is forgettable.

You produce a wide range (30 titles), from safe to polarizing, so the author can see several kinds of promises before choosing.

## What You Need

Ask the user for:
- **Video topic or script** — what the video covers
- **Key result or insight** — the most interesting thing in the video
- **Target audience** — who should click (pull from CLAUDE.md if available, don't re-ask)

If the user provides a script or brief, extract what you need from it. Don't ask for information that's already there.

## Step 1: Collect the Raw Material

Before writing anything, list what the video actually contains.

**The promise**

| Element | Question |
| --- | --- |
| Transformation | What changes for the viewer: skills, career, income, time, way of working? |
| Big idea | The one claim from the video people would repeat to a friend |
| Audience | Who gains, and what they want or fear |
| Contrast | Where a modest effort leads to an outsized result, or where the advice goes against the grain |

**The facts**

| Fact | Examples |
| --- | --- |
| Tool / technology | Claude Code, Cursor, n8n, a specific feature or version |
| Input | one prompt, a screenshot, an old codebase, zero lines of code |
| Output | a working app, a deployed API, a dashboard, an automation |
| Time / effort | 20 minutes, one evening, 2 hours a day for 6 months |
| Number | 5 mistakes, 3 workflows, 40 % faster, €200 a month saved |
| Verdict | worth it or not, winner of a comparison, what broke |

Titles can only use facts from this list. No fact, no number: never invent a duration, an amount or a result the video doesn't show.

## Step 2: 20 Structured Titles

Rotate through three formulas, never the same one twice in a row.

### A. Bold statement + (what's behind it)
A short, strong claim, then the explanation or method in parentheses.
- "The End of the Junior Developer (and What Replaces It)"
- "Your To-Do List Is the Problem (Do This Instead)"

### B. How to + desirable outcome + (mechanism)
The result the viewer wants, then how, or the angle nobody mentions.
- "How to Learn Any Framework in a Weekend (The 3-Pass Method)"
- "How to Get Hired Without a Degree (What Recruiters Actually Check)"

### C. Time frame or number + (what to focus on)
A concrete amount of time or effort, then where to put it.
- "2 Hours a Day for 6 Months (The Skills Worth Learning Now)"
- "From Screenshot to Working Page in 18 Minutes (Full Build)"

Spread these levers across the 20 titles, each in several titles:

| Lever | How | Wording |
| --- | --- | --- |
| Time frame | A concrete, believable duration | "in 6 months", "2 hours a day", "in 30 days" |
| Transformation | A visible change in the viewer | "change your career", "you won't work the same way" |
| Insider knowledge | What most people miss | "what nobody tells you", "most people ignore this" |
| Status | Getting ahead | "ahead of 99 % of developers", "irreplaceable" |

And these contrasts, in several titles:
- **Small input, big output:** "2 hours a day" → "a new career", "one screenshot" → "a full app".
- **Unexpected pairing:** two ideas that don't usually go together ("your career as a video game").
- **Counterintuitive advice:** "stop learning new frameworks", "do less to ship more".

## Step 3: 10 Free Titles

Ten more that leave the formulas aside: the most clickable titles you can find for this video, noticeably different from the first twenty. Draw on these patterns, at least five of them:

### 1. Curiosity Gap
Create an information gap the viewer needs to close. Say enough to intrigue, not enough to satisfy.
- "The [Thing] Nobody Talks About in [Field]"
- "I Tested [X] for [Time Period]. Here's What Happened."

### 2. Result / Outcome
Lead with the result. Numbers and specifics beat vague claims.
- "How I [Achieved Result] in [Timeframe]"
- "[Specific Number] [Things] That [Changed/Built/Fixed] My [X]"

### 3. Challenge / Contrarian
Take a position that pushes against conventional wisdom. The title itself is an argument.
- "[Popular Thing] Is Wasting Your Time. Do This Instead."
- "Stop [Common Advice]. Here's Why."

### 4. Specificity / Numbers
Concrete numbers make titles feel real and actionable. Odd numbers outperform even ones.
- "[Number] [Things] I Wish I Knew Before [X]"
- "The [Number]-Step System for [Outcome]"

### 5. Comparison
Position two things against each other. Creates instant context and stakes.
- "[Thing A] vs [Thing B]: Which Actually Works?"
- "I Switched from [X] to [Y]. The Difference Is Huge."

### 6. Story-Driven
Personal narrative hooks. The viewer clicks to hear what happened.
- "I [Did Unexpected Thing] and [Surprising Result]"
- "What Happened When I [Bold Action]"

### 7. How-To / Tutorial
Direct value promise. Works best when the outcome is specific.
- "How to [Achieve Specific Result] (Step by Step)"
- "The Complete Guide to [X] for [Audience]"

For tech, tutorial and tool videos, the content type points to the strongest pattern:

| The video is… | Lead with |
| --- | --- |
| A build / demo | I built {output} with {tool} from {input} |
| A fast transformation | From {input} to {output} in {time} |
| A tool review | I used {tool} for {time}: {verdict} |
| A comparison | {tool A} vs {tool B} for {use case} |
| Time or money saved | {task}: from {before} to {after} with {tool} |

## Writing the Variables

Always use the precise version:

| Vague | Precise |
| --- | --- |
| an app | a complete booking app |
| quickly | in 20 minutes |
| a few prompts | 3 prompts |
| AI | Claude Code |
| saves money | €200 a month |
| better | 40 % faster |

Exact numbers beat round ones ("18 minutes" beats "under 20 minutes"), and the name of the tool beats the name of the category.

## Polish

- **Front-load the searchable term.** When the video is about a tool or technology, its name sits in the first 40 characters.
- **Parentheses carry the method or the bonus:** "(Do This Instead)", "(template included)", "(full code)", "(step by step)".
- **Show the verdict's direction.** For reviews and comparisons, hint at the outcome: "the cheaper one won" beats "the winner surprised me".

## Output Format

Present each title with:

```
**[Title]**
Pattern: [which formula or pattern]
Why it works: [one sentence — what makes this clickable for the target audience]
```

## After the List

Recommend your **top 3 picks** and explain why. Pick three titles that make three different promises (for example one statement, one how-to, one free title), so an A/B test tells the author which kind of promise their audience prefers. Consider:
- Which ones have the strongest curiosity gap?
- Which ones most clearly signal value to the target audience?
- Which ones would stand out in a feed full of similar content?

If the user has existing videos (check CLAUDE.md or ask), factor in what title styles have worked for their channel.

## Rules

- **High conviction, never a lie.** Be bold, take sides, be polarizing when it fits — but every title is a promise the video actually keeps.
- **30 distinct titles.** No two titles that only differ by a word; no formula twice in a row.
- **The core idea stays.** Every title is about this video, not a more clickable neighbouring topic.
- Every title under 60 characters when possible (displays fully on mobile), 70 at most
- No ALL CAPS words — YouTube audiences read it as shouting
- No generic filler words ("Amazing," "Incredible," "Mind-Blowing") unless they genuinely fit
- No vague promises: "How I Improved My Workflow" loses to "My Deployments Went From 1 Hour to 5 Minutes"
- Don't use the creator's name in the title unless they're already well-known enough for it to drive clicks
- If the video topic is niche, lean into specificity over broad appeal — the right 10K viewers beat 100K wrong ones
