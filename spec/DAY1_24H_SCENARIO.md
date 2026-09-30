# DAY 1 — 24-HOUR OPERATING SCENARIO

This is a behavioral prototype, not a literal requirement to run every hour.

## 08:00 — State refresh
Jarvis reads STATE.json, the current strategy, latest decisions and unfinished backlog.

Output:
- STATE_DELTA.md
- prioritized task queue

Goal:
Do not start by creating content. First determine what is strategically unresolved.

## 09:00 — Strategic framing
Creative Director selects one high-leverage question.

Example for Day 1:
"What must be true for an audience to begin perceiving Viktor Mir as a serious painter without weakening tattoo revenue?"

Output:
- STRATEGIC_QUESTION_001.md

## 10:00 — Research brief
Research role creates a narrow research plan:
- comparable artist career structures;
- artist/tattoo crossovers;
- gallery/editorial presentation patterns;
- pricing/signaling mechanisms;
- audience transition patterns.

Important:
Research is not trend scraping. It is evidence gathering for one strategic question.

Output:
- RESEARCH_BRIEF_001.md
- SOURCES_001.csv

## 12:00 — Hypothesis lab
Generate multiple genuinely different strategic hypotheses.

Each hypothesis must contain:
- mechanism;
- expected benefit;
- risk;
- evidence required;
- 30-day test;
- 12-month implication.

Output:
- HYPOTHESES_001.md

## 13:30 — Red-team critique
A critic role attacks the hypotheses:
- generic?
- too dependent on personal-brand clichés?
- confuses commercial tattoo audience with art buyers?
- requires fake status signaling?
- impossible to sustain?
- visually dependent despite the text-only system?

Kill weak options.

Output:
- RED_TEAM_001.md

## 15:00 — Editorial translation
The surviving strategic ideas are translated into text-only executable structures:
- series concepts;
- post/story/reel scripts without producing media;
- artist notes;
- interview prompts;
- portfolio narratives;
- website architecture;
- exhibition/project concepts;
- editorial calendars.

Output:
- EDITORIAL_ACTIONS_001.md

## 17:00 — Commercial bridge
A business role checks whether the art strategy preserves income.

Questions:
- Does this reduce tattoo booking too abruptly?
- Can tattoo work be made more selective/high-value over time?
- What art activity needs protected time?
- What signals should be separated between tattoo buyers and art collectors?

Output:
- COMMERCIAL_BRIDGE_001.md

## 18:30 — Archive task design
Jarvis decides what information/material Viktor should eventually supply.

It does not ask for everything.
It asks only for material that unlocks the next strategic step.

Output:
- MATERIAL_REQUEST_001.md

## 20:00 — Synthesis
Creative Director merges the useful work into one decision memo.

Output:
- DECISION_MEMO_001.md

The memo contains:
- what Jarvis now believes;
- what remains uncertain;
- what not to do;
- one recommended experiment;
- autonomous next work.

## 21:00 — Daily report
Jarvis writes the human-facing DAILY_REPORT.

It should take 3–7 minutes to read.
No chain-of-thought. Only findings, decisions, evidence, files and next actions.

## 23:00 — Cheap background queue
Low-cost model tasks:
- clean notes;
- normalize tags;
- update CSV/JSON;
- deduplicate ideas;
- summarize source notes;
- maintain indexes.

No expensive strategic model unless a blocker is discovered.

## 00:00 — Roll state forward
Update:
- STATE.json
- DECISIONS.md
- BACKLOG.csv
- IDEA_LEDGER.md

The next day starts from the updated state instead of rereading the entire history.
