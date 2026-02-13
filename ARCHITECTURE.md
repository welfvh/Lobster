# Lobster Multi-Agent Infrastructure Architecture

> Last updated: 2026-02-13
> VPS: Hetzner CAX21 (8GB RAM, 4 ARM64 CPUs, 80GB disk)
> OS: Debian Linux 6.1.0-43-arm64

---

## System Overview

```
    EXTERNAL SERVICES                          HETZNER VPS (162.55.60.42)
    ================                           ==========================

                                      +------------------------------------------+
  +-------------+                     |                                          |
  |  Telegram   |<----- HTTPS ------->|  lobster_bot.py    amber_bot.py          |
  |  Bot API    |                     |    (polling)          (polling)           |
  +-------------+                     |       |                   |               |
                                      |       v                   v               |
  +-------------+                     |  ~/messages/inbox/   ~/messages/inbox/    |
  |  Slack API  |<----- HTTPS ------->|       |  (source:     (source:            |
  | (Web API)   |                     |       |  telegram)    telegram-amber)      |
  +-------------+                     |       |                   |               |
                                      |  slack_gateway.py         |               |
  +-------------+                     |    (20s poll)             |               |
  |  Claude     |<----- HTTPS ------->|       |                   |               |
  |  API        |                     |       v                   v               |
  | (Anthropic) |                     |  +--------+  +-------+  +-------+        |
  +-------------+                     |  |Lobster |  | Klaus |  | Amber |        |
                                      |  |tmux:   |  | tmux: |  | tmux: |        |
  +-------------+                     |  |hyperion|  | klaus |  | amber |        |
  | Cloudflare  |<----- HTTPS ------->|  +--------+  +-------+  +-------+        |
  |  Workers    |                     |  +--------+  +--------+                  |
  | context-mcp |                     |  | Steve  |  | Cicero |   Jordan         |
  | arena-mcp   |                     |  | tmux:  |  | tmux:  |  (cron only)     |
  | potential    |                     |  | steve  |  | cicero |                  |
  +-------------+                     |  +--------+  +--------+                  |
                                      |                                          |
  +-------------+                     |  inbox_server_http.py  :8741             |
  | Mac Claude  |<--- HTTP/MCP ------>|    (Streamable HTTP MCP bridge)          |
  |  Code       |                     |                                          |
  +-------------+                     |  cron: watchdog.sh (*/5min)              |
                                      |  cron: scheduled jobs (5 active)         |
  +-------------+                     |                                          |
  | GitHub API  |<----- HTTPS ------->|  gh CLI (PAT: welfvh)                   |
  +-------------+                     +------------------------------------------+
```

---

## Process Map

### Always-On Processes (5 tmux sessions + 4 daemons)

```
  TMUX SESSIONS                           DAEMON PROCESSES
  =============                           ================

  "hyperion" ---- Lobster (interactive)   lobster_bot.py ---- Telegram bot
       |          claude --dangerously-        PID: 218393
       |          skip-permissions             Watches: ~/messages/outbox/
       |          (interactive mode)           Writes:  ~/messages/inbox/
       |
  "klaus" ------ agent-loop.sh klaus      amber_bot.py ------ Telegram bot
       |          claude -p (print mode)       PID: 8063
       |          --continue between loops     Watches: ~/messages/outbox/
       |          30s wait_for_messages        Writes:  ~/messages/inbox/
       |                                       Source:  "telegram-amber"
  "steve" ------ agent-loop.sh steve
       |          claude -p (print mode)  slack_gateway.py --- Slack gateway
       |          --continue between loops     PID: 210158
       |          30s wait_for_messages        Polls: 9 Slack channels (20s cycle)
       |                                       Routes to agent inboxes
  "cicero" ----- agent-loop.sh cicero          Watches: all agent outboxes
       |          claude -p (print mode)
       |          --continue between loops inbox_server_http.py - HTTP MCP
       |          30s wait_for_messages        PID: 7906
       |                                       Port: 8741
  "amber" ------ amber-loop.sh                 Bearer token auth
                  claude -p (print mode)       Exposes Lobster inbox to Mac
                  --continue between loops
                  30s wait_for_messages
```

### Scheduled Processes (cron)

```
  CRON SCHEDULE                    PROCESS                         TARGET
  =============                    =======                         ======

  */5 * * * *                      watchdog.sh                     Lobster + Amber
                                   Checks heartbeat files,         heartbeat monitoring
                                   restarts stale sessions

  0 0 * * *                        run-job.sh nightly-github-      GitHub backup
                                   backup                          (claude -p, max 15 turns)

  15 5 * * *                       run-job.sh amber-morning-       Amber companion
                                   orientation                     check-in

  0 12 * * *                       run-job.sh amber-midday-        Amber companion
                                   checkin                         check-in

  0 15 * * *                       run-job.sh amber-afternoon-     Amber companion
                                   checkin                         check-in

  0 21 * * *                       run-job.sh amber-evening-       Amber companion
                                   winddown                        check-in
```

### Agent Definitions (agents.json)

```
  AGENT        ROLE                  MODE         METHOD       SLACK CHANNELS
  =====        ====                  ====         ======       ==============
  Lobster      CTO                   always-on    interactive  #engineering, #ship-log,
                                                               #alerts, #general, #random
  Amber        Personal Companion    always-on    p-loop       (Telegram only)
  Klaus        Chief of Staff        always-on    p-loop       #standup, #engineering,
                                                               #alerts
  Jordan B.    CFO                   scheduled    run-once     #standup
                                     (M-F 8am)
  Steve        Head of Product       always-on    p-loop       #engineering, #research
  Cicero       CMO                   always-on    p-loop       #content
```

---

## Message Flow

### Telegram to Lobster

```
  User Phone                 VPS
  ==========                 ===

  Telegram App               lobster_bot.py (long-poll Telegram API)
       |                          |
       |--- user sends msg ------>|
       |                          |--- write JSON ---> ~/messages/inbox/{id}.json
       |                          |                         |
       |                          |                    MCP: wait_for_messages()
       |                          |                    (inotify watcher)
       |                          |                         |
       |                          |                    Lobster Claude session
       |                          |                    reads + processes msg
       |                          |                         |
       |                          |                    MCP: send_reply()
       |                          |                         |
       |                          |<-- watchdog read -- ~/messages/outbox/{id}.json
       |<--- bot.send_message ----|
       |                          |--- delete file after send
```

### Telegram to Amber

```
  User Phone                 VPS
  ==========                 ===

  Telegram App               amber_bot.py (long-poll Telegram API)
  (@AmberBot)                     |
       |--- user sends msg ------>|
       |                          |--- write JSON ---> ~/messages/inbox/{id}.json
       |                          |    source: "telegram-amber"
       |                          |                         |
       |                          |                    Amber inbox server
       |                          |                    routes to amber-inbox/
       |                          |                         |
       |                          |                    Amber Claude session
       |                          |                    processes msg
       |                          |                         |
       |                          |<-- watchdog read -- ~/messages/outbox/{id}.json
       |<--- bot.send_message ----|    source: "telegram-amber"
```

### Slack to Agents (channel-based routing)

```
  Slack                      VPS
  =====                      ===

  monasticworkspace          slack_gateway.py (polls conversations.history)
  .slack.com                      |
       |                          |--- poll every 20s + 1.5s/channel delay
       |                          |
       |  #engineering ---------->|--- route to ---> ~/messages/inbox/
       |                          |                  (Lobster is primary)
       |  #standup -------------->|--- route to ---> ~/messages/klaus-inbox/
       |  #research ------------->|--- route to ---> ~/messages/steve-inbox/
       |  #content -------------->|--- route to ---> ~/messages/cicero-inbox/
       |  #alerts --------------->|--- route to ---> ~/messages/inbox/
       |  #ship-log ------------->|--- route to ---> ~/messages/inbox/
       |  #general -------------->|--- route to ---> ~/messages/inbox/
       |  #random --------------->|--- route to ---> ~/messages/inbox/
       |                          |
       |                          |  Agent processes + calls send_reply(source="slack")
       |                          |
       |<-- chat_postMessage -----|<- watches ~/messages/{agent}-outbox/*.json
       |  (chat:write.customize)  |   Uses agent persona (username + icon_url)
       |  Posts as agent persona  |
```

### Mac Claude Code to Lobster (HTTP MCP Bridge)

```
  Mac (Local)                VPS
  ===========                ===

  Claude Code                inbox_server_http.py (:8741)
       |                          |
       |--- HTTP POST /mcp ------>|--- Bearer token auth check
       |    Streamable HTTP       |
       |    MCP protocol          |--- delegates to inbox_server.py
       |                          |    (same MCP server as local Lobster)
       |                          |
       |<--- MCP response --------|
```

### Inter-Agent IPC

```
  Agent A                    File System                Agent B
  =======                    ===========                =======

  Lobster                    ~/messages/                Klaus
       |                          |                          |
       |-- send_to_klaus() ------>|                          |
       |                     writes JSON to                  |
       |                     ~/messages/klaus-inbox/         |
       |                          |                          |
       |                          |--- inotify ------------>|
       |                          |    wait_for_messages()   |
       |                          |                          |
       |                          |<-- send_to_lobster() ---|
       |                     writes JSON to                  |
       |<--- inotify -------  ~/messages/inbox/              |
```

---

## File System Layout

```
  ~/messages/
  +-- inbox/                    Lobster incoming (Telegram, Slack, IPC)
  +-- outbox/                   Lobster outgoing (watched by bots + gateway)
  +-- processed/                Lobster processed messages
  +-- sent/                     Lobster sent reply archive
  +-- dead-letter/              Failed messages after 5 retries
  +-- audio/                    Voice message audio files (.ogg)
  +-- images/                   Photo message images (.jpg)
  +-- files/                    Document attachments
  +-- task-outputs/             Scheduled job outputs
  +-- tasks.json                Lobster task list
  +-- slack-gateway-state.json  Slack polling last-seen timestamps
  +--
  +-- amber-inbox/              Amber incoming
  +-- amber-outbox/             Amber outgoing
  +-- amber-processed/          Amber processed
  +-- amber-sent/               Amber sent
  +--
  +-- klaus-inbox/              Klaus incoming
  +-- klaus-outbox/             Klaus outgoing
  +-- klaus-processed/          Klaus processed
  +-- klaus-sent/               Klaus sent
  +--
  +-- steve-inbox/              Steve incoming
  +-- steve-outbox/             Steve outgoing
  +-- steve-processed/          Steve processed
  +-- steve-sent/               Steve sent
  +--
  +-- cicero-inbox/             Cicero incoming
  +-- cicero-outbox/            Cicero outgoing
  +-- cicero-processed/         Cicero processed
  +-- cicero-sent/              Cicero sent

  ~/lobster/
  +-- config/
  |   +-- agents.json           Agent definitions (6 agents)
  |   +-- config.env            Telegram + Amber bot tokens
  |   +-- slack.env             Slack bot token + channel IDs
  |   +-- mcp-http-auth.env     HTTP MCP bridge bearer token
  +-- scripts/
  |   +-- agent-loop.sh         Generic agent loop (claude -p)
  |   +-- amber-loop.sh         Amber-specific loop
  |   +-- watchdog.sh           Health monitor (cron */5min)
  +-- scheduled-tasks/
  |   +-- jobs.json             Scheduled job definitions
  |   +-- run-job.sh            Job executor (claude -p --max-turns 15)
  |   +-- sync-crontab.sh       Syncs jobs.json to system crontab
  |   +-- tasks/                Job instruction files (.md)
  |   +-- logs/                 Job execution logs
  +-- src/
      +-- bot/lobster_bot.py    Lobster Telegram bot
      +-- bot/amber_bot.py      Amber Telegram bot
      +-- slack/slack_gateway.py Multi-agent Slack gateway
      +-- mcp/agent_inbox_server.py  Universal MCP inbox server
      +-- mcp/inbox_server_http.py   HTTP MCP bridge (:8741)
```

---

## MCP Server Connections Per Agent

```
  AGENT       MCP SERVERS CONNECTED                  TRANSPORT
  =====       =====================                  =========

  Lobster     hyperion-inbox (lobster)               stdio (local)
              context-mcp                            HTTP (Cloudflare)
              arena-mcp                              HTTP (Cloudflare)
              potential                               HTTP (Cloudflare)
              (configured in Claude Code interactive session)

  Klaus       klaus-inbox                            stdio (local)
              context-mcp                            HTTP (Cloudflare)  <-- CANDIDATE FOR REMOVAL

  Steve       steve-inbox                            stdio (local)
              context-mcp                            HTTP (Cloudflare)  <-- CANDIDATE FOR REMOVAL

  Cicero      cicero-inbox                           stdio (local)
              context-mcp                            HTTP (Cloudflare)  <-- CANDIDATE FOR REMOVAL

  Amber       amber-inbox                            stdio (local)
              (no Cloudflare connections)

  Jordan      (no workspace — scheduled only)
```

---

## External Dependencies

### Cloudflare Workers

| Worker | URL | Purpose | Called By |
|--------|-----|---------|-----------|
| context-mcp | context-mcp.potential.workers.dev | Personal context, self-knowledge | Lobster, Klaus*, Steve*, Cicero* |
| arena-mcp | arena-mcp.potential.workers.dev | Are.na channel integration | Lobster |
| potential | potential.potential.workers.dev | Screen time, calendar data | Lobster |

*Klaus, Steve, and Cicero have context-mcp configured but likely do not actively use it.

### Telegram API

| Bot | Token Prefix | Allowed Users | Source ID |
|-----|-------------|---------------|-----------|
| Lobster Bot | 8532193747 | 716197220 | "telegram" |
| Amber Bot | 8536986913 | 716197220 | "telegram-amber" |

### Slack API

| Property | Value |
|----------|-------|
| Workspace | monasticworkspace.slack.com |
| Bot | Lobster (app_id: A0AEXTS4NFK) |
| Bot User | U0AFD8WJJFJ |
| Channels | 9 (#general, #random, #engineering, #research, #content, #wellness, #standup, #ship-log, #alerts) |
| Key Scopes | chat:write, chat:write.customize, channels:history, channels:read |

### GitHub API

| Property | Value |
|----------|-------|
| CLI | gh v2.86.0 at ~/bin/gh |
| User | welfvh |
| Auth | Fine-grained PAT (welfvh repos only) |
| Lobster Repo | welfvh/Lobster (public fork of SiderealPress/lobster) |

---

## Claude API Usage Analysis

This is the most significant cost driver of the entire system.

### How Agent Loops Work

Each always-on agent runs in a bash `while true` loop:

```
  1. agent-loop.sh calls: claude -p "<prompt>" --continue
  2. Claude CLI sends request to Anthropic API (input: system prompt + tools + history)
  3. Claude calls wait_for_messages(timeout=30) via MCP
  4. MCP server blocks for 30 seconds (inotify wait)
  5. Returns "no messages" or processes messages
  6. Claude CLI outputs response to file
  7. Loop sleeps 2 seconds
  8. GOTO 1
```

**Total cycle time: ~38 seconds** (30s MCP wait + ~6s Claude processing + 2s sleep)

### Calls Per Day Per Agent

```
  Seconds per day:     86,400
  Seconds per cycle:       38
  Cycles per day:       2,274  (86400 / 38)
```

### Always-On Agents: 5

```
  AGENT       CYCLES/DAY    MODE
  =====       ==========    ====
  Lobster      2,274        interactive (different pattern, but similar API usage)
  Klaus        2,274        p-loop
  Steve        2,274        p-loop
  Cicero       2,274        p-loop
  Amber        2,274        p-loop
  ---------------------------------
  TOTAL       11,370        API calls/day from polling alone
```

### Scheduled Jobs: 6 calls/day

```
  JOB                         FREQUENCY    CALLS/DAY
  ===                         =========    =========
  nightly-github-backup       1x/day       1 (max 15 turns)
  amber-morning-orientation   1x/day       1 (max 15 turns)
  amber-midday-checkin        1x/day       1 (max 15 turns)
  amber-afternoon-checkin     1x/day       1 (max 15 turns)
  amber-evening-winddown      1x/day       1 (max 15 turns)
  watchdog.sh                 288x/day     0 (no Claude API calls)
  -------------------------------------------------------
  TOTAL                                    ~5 API calls/day
```

### Token Estimation Per Cycle

Each `claude -p` call sends to the Anthropic API:

```
  COMPONENT                              EST. TOKENS    NOTES
  =========                              ===========    =====
  System prompt (CLAUDE.md)              1,500-3,000    Agent instructions
  Soul/persona file (soul.md)              500-1,500    Personality definition
  MCP tool schemas                       3,000-5,000    ~30 tool definitions with
                                                        JSON schemas (inbox, tasks,
                                                        scheduled jobs, IPC, etc.)
  Conversation history (--continue)      1,000-50,000   Grows over time until
                                                        session resets
  User prompt                              50-100       "Call wait_for_messages..."
  ---------------------------------------------------------------
  INPUT per cycle (fresh session):       ~6,000-10,000  tokens
  INPUT per cycle (continued, avg):      ~15,000-30,000 tokens
  INPUT per cycle (continued, max):      ~50,000+       tokens

  OUTPUT per cycle (no messages):        100-300        "No messages received..."
  OUTPUT per cycle (with messages):      200-2,000      Processing + reply
```

### Daily Token Estimates

```
  SCENARIO                   INPUT TOKENS/DAY       OUTPUT TOKENS/DAY
  ========                   ================       =================
  Conservative (fresh)       11,370 x 8K  = 91M     11,370 x 200  =  2.3M
  Realistic (continued)      11,370 x 20K = 227M    11,370 x 300  =  3.4M
  Worst case (long history)  11,370 x 40K = 455M    11,370 x 500  =  5.7M
```

### Cost Estimates (Claude Sonnet 4 pricing: $3/1M input, $15/1M output)

```
  SCENARIO        INPUT COST/DAY   OUTPUT COST/DAY   TOTAL/DAY   TOTAL/MONTH
  ========        ==============   ===============   =========   ===========
  Conservative    $0.27            $0.03             $0.30       $9.12
  Realistic       $0.68            $0.05             $0.73       $22.18
  Worst case      $1.37            $0.09             $1.46       $43.80
```

**NOTE:** These estimates assume Claude Sonnet 4 pricing. If agents use Claude Opus 4 ($15/1M input, $75/1M output), costs multiply by 5x:

```
  SCENARIO        OPUS TOTAL/DAY   OPUS TOTAL/MONTH
  ========        ==============   ================
  Conservative    $1.52            $45.60
  Realistic       $3.66            $109.80
  Worst case      $7.28            $218.40
```

### Cost Breakdown By Agent (Realistic Scenario, Sonnet)

```
  AGENT       CYCLES    INPUT TOKENS    OUTPUT TOKENS   COST/DAY   COST/MONTH
  =====       ======    ============    =============   ========   ==========
  Lobster     2,274     45.5M           0.68M           $0.15      $4.44
  Klaus       2,274     45.5M           0.68M           $0.15      $4.44
  Steve       2,274     45.5M           0.68M           $0.15      $4.44
  Cicero      2,274     45.5M           0.68M           $0.15      $4.44
  Amber       2,274     45.5M           0.68M           $0.15      $4.44
  Scheduled   5         0.5M            0.075M          <$0.01     $0.05
  -----------------------------------------------------------------------
  TOTAL       11,375    227.5M          3.4M            $0.73      $22.18
```

### Key Insight: The Idle Polling Problem

The overwhelming majority of API calls (~95%+) are idle polls where no messages are waiting. Each poll still sends the full system prompt, tool schemas, and conversation history to the API. **The system is paying full price for silence.**

---

## Cloudflare Workers Usage Analysis

### How Workers Are Called

Each MCP connection to a Cloudflare Worker makes requests when:
1. **Connection initialization** - tool listing on session start
2. **Tool calls** - when the agent actually uses a tool

### context-mcp Connections

Currently connected to: Lobster, Klaus, Steve, Cicero (4 agents)

```
  AGENT       CYCLES/DAY    INIT REQUESTS    TOOL CALLS (EST)    TOTAL REQ/DAY
  =====       ==========    =============    ================    =============
  Lobster     2,274         2,274            ~10-50              ~2,300
  Klaus       2,274         2,274            ~0-5                ~2,280
  Steve       2,274         2,274            ~0-5                ~2,280
  Cicero      2,274         2,274            ~0-5                ~2,280
  -----------------------------------------------------------------------
  TOTAL                                                          ~9,140/day
```

**NOTE:** Klaus, Steve, and Cicero almost certainly never call context-mcp tools. Their MCP initialization requests alone generate ~6,840 wasted Cloudflare Worker invocations per day (~205,000/month).

### Cloudflare Free Tier Limits

| Resource | Free Tier | Current Usage (est.) |
|----------|-----------|---------------------|
| Worker requests | 100,000/day | ~9,140/day (context-mcp alone) |
| CPU time | 10ms per request | Well within limits |

Removing context-mcp from Klaus, Steve, and Cicero would save ~6,840 requests/day.

---

## Recommendations for Optimization

### 1. Remove context-mcp from non-using agents (IMMEDIATE)

Klaus, Steve, and Cicero have `context-mcp` in their `.mcp.json` but do not actively use context tools. Each connection generates ~2,274 initialization requests/day to Cloudflare Workers.

**Savings:** ~6,840 Cloudflare Worker requests/day (~205,000/month)

### 2. Increase wait_for_messages timeout (EASY)

Currently 30 seconds. Increasing to 120 seconds would reduce cycles from 2,274/day to ~700/day per agent.

```
  Current:  30s timeout = 2,274 cycles/day/agent = 11,370 total
  120s:    120s timeout =   706 cycles/day/agent =  3,530 total
  300s:    300s timeout =   286 cycles/day/agent =  1,430 total
```

**Savings at 120s:** ~69% reduction in API calls (~$15/month saved at Sonnet pricing)

**Trade-off:** Response latency increases from ~38s to ~128s for new messages. For agents like Klaus, Steve, and Cicero that rarely receive messages, this is acceptable.

### 3. Differentiate agent timeouts by activity level (MODERATE)

```
  AGENT       CURRENT TIMEOUT   RECOMMENDED    RATIONALE
  =====       ===============   ===========    =========
  Lobster     30s (interactive) 30s            Primary agent, needs responsiveness
  Amber       30s               60s            Companion, slight delay OK
  Klaus       30s               120s           Chief of Staff, mostly async
  Steve       30s               300s           Research, very async
  Cicero      30s               300s           Content, very async
```

### 4. Implement message-driven wakeup instead of polling (SIGNIFICANT)

Instead of each agent polling every 38 seconds, implement a push-based system:
- Agent calls `wait_for_messages(timeout=3600)` (1 hour)
- When a message arrives, the bash loop detects it and sends SIGUSR1 to the claude process
- Or: use a lightweight watcher process that only spawns `claude -p` when messages exist

**Savings:** Could reduce idle API calls by 95%+

### 5. Monitor --continue conversation growth (IMPORTANT)

The `--continue` flag means conversation context grows across loop iterations. After many cycles, input tokens per call could be 50K+ tokens. Periodic session resets (e.g., after 100 cycles or when context exceeds a threshold) would keep costs predictable.

### 6. Consolidate agent outbox watching (MINOR)

The Slack gateway watches all agent outboxes using inotify (watchdog library), which is efficient. No change needed. The Telegram bots each watch the shared outbox and filter by source, which is also fine for the current scale.

---

## Resource Usage Summary

### Memory (as of 2026-02-13)

```
  Total: 7.6 GB
  Used:  2.8 GB (37%)
  Free:  4.8 GB available

  PROCESS                 EST. MEMORY
  =======                 ===========
  5x Claude CLI sessions  ~2.0 GB (largest consumers)
  lobster_bot.py          ~55 MB
  amber_bot.py            ~53 MB
  slack_gateway.py        ~31 MB
  inbox_server_http.py    ~58 MB
  5x MCP inbox servers    ~50 MB (stdio, spawned by Claude)
  OS + buffers            ~550 MB
```

### Monthly Costs

```
  ITEM                    COST/MONTH
  ====                    ==========
  Hetzner CAX21 VPS       ~$7.50
  Claude API (Sonnet)     ~$22 (realistic estimate)
  Claude API (Opus)       ~$110 (if using Opus)
  Cloudflare Workers      $0 (free tier)
  Telegram Bot API        $0 (free)
  Slack API               $0 (free tier)
  GitHub (PAT)            $0 (free)
  ----------------------------------------
  TOTAL (Sonnet)          ~$30/month
  TOTAL (Opus)            ~$118/month
```
