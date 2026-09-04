# Teaching Notes

- The learner's objective is to define systems and feature outcomes before implementation, then use strict expected failures with a TDD loop.
- Typeforge itself shows advanced Python and testing fluency, so lessons can use compiler seams, typed results, and architecture rules without first teaching pytest basics.
- Do not treat material as learned until the learner completes an exercise or explains the distinction back.

## First lesson design

- **Audience and job:** Typeforge's author; turn the next feature idea into one stable executable contract.
- **Form:** A short explainer with a seam-classification quiz and a contract-drafting tool.
- **Register:** Quiet, workmanlike “proof ledger”; the visual language comes from tests changing state.
- **Fidelity:** Use real Typeforge principles, test names, commands, and historical migration evidence.
- **Interaction:** Immediate quiz feedback, a locally saved contract worksheet, copying, and a theme toggle.

### Visual direction

- **Color:** proof blue `#0B62B5`, verdict green `#08765B`, pending amber `#A54D00`, cool paper `#F5F8FC`, ink `#18232D`, rule `#CAD7E3`.
- **Type:** Iowan/Palatino serif for the lesson argument, Avenir/system sans for explanatory prose, and the platform monospace for executable evidence.
- **Layout:** A narrow reading column opens into wider “evidence benches” for code, seam comparisons, and the worksheet. A ruled state rail makes the specification-to-regression transition visible.

## Second lesson design

- **Audience and job:** An experienced Typeforge author collaborating with a coding agent before and during a feature slice.
- **Form:** A compact workflow lesson with commitment gates, a Typeforge walkthrough, and a copyable agent prompt.
- **Register:** The same proof-ledger course language, organized as two interlocking tracks: discovery and delivery.
- **Fidelity:** Preserve the learner's proposed progression while separating domain facts from premature code data structures.
- **Interaction:** Short KEEP/WAIT decisions followed by a reusable session prompt.
