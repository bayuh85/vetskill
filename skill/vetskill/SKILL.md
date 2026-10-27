---
name: vetskill
description: Vet a third-party agent skill, plugin or MCP config with vetskill before installing or enabling it. Use when the user asks to install, add or try a skill, plugin or MCP server.
allowed-tools: Bash(vetskill scan:*), Bash(vetskill review:*), Bash(vetskill reveal:*), Bash(git clone:*), Read
---

# Vet before install

1. Clone or download the skill into a temporary folder. Do not copy it into a skills directory yet.
2. Run `vetskill scan <folder>`. Exit code 1 means at least one high-severity finding.
3. If anything is flagged, run `vetskill review <folder>` for a model second opinion and show the user the findings with their `file:line` locations.
4. Install only when the verdict is PASS, or when the user has read every finding and still says yes.
5. Never run the skill's own scripts while vetting it.
