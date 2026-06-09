# Autonomous Multi-Channel Video Generation Pipeline (AutoTube-12)

This document serves as the absolute ground-truth context and system architecture definition for building a 100% autonomous, zero-human-intervention YouTube Shorts/TikTok video generation and scheduling system using Python. 

Always adhere to the architecture, directory structures, and data models defined below when generating code or adding features.

---

## 1. System Core Philosophy
* **Zero Human Intervention:** Once a week, the admin inputs raw topics into the database. The system automatically processes, renders, and schedules everything else.
* **Modular Architecture:** Text generation, audio processing, video rendering, and publishing must be decoupled modules.
* **Strict Data Types:** All communication between LLM and backend layers must use strict JSON parsing. Talkative AI outputs will crash the pipeline.

---

## 2. Technical Stack & Dependencies
* **Core Language:** Python 3.10+
* **Database:** SQLite (Lightweight, local file-based, perfect for pipeline state management)
* **LLM Layer:** Anthropic API (Claude 3.5 Sonnet) / OpenAI API
* **TTS Layer:** ElevenLabs API (using high-quality multilingual models + timestamp synthesis)
* **Video Automation:** MoviePy (Python library for programmatically generating video layers)
* **Publishing Layer:** YouTube Data API v3 (Google API Client for Python)

---

## 3. System Architecture & Directory Layout

```text
autotube-12/
│
├── config/
│   ├── __init__.py
│   ├── settings.py           # API keys, global constants, limits
│   └── channels_config.json  # Meta configs for the 12 independent channels
│
├── core/
│   ├── __init__.py
│   ├── database.py           # SQLite connection, migration, states
│   ├── llm_engine.py         # Prompt engineering, script & SEO generator
│   ├── tts_engine.py         # ElevenLabs integration & timestamp extraction
│   ├── video_editor.py       # MoviePy engine, subtitles burner, overlay manager
│   └── youtube_uploader.py   # OAuth2 token rotator and video scheduler
│
├── assets/
│   ├── backgrounds/          # Categorized stock video footage pools per channel
│   ├── fonts/                # Custom TTF fonts for styled subtitles (e.g., Montserrat-Bold)
│   └── outputs/              # Temp directory for finalized .mp4 renders
│
├── data/
│   └── pipeline.db           # SQLite database file
│
├── main.py                   # Central orchestrator / cron entrypoint
├── requirements.txt
└── context.md                # This file
4. Database Schema (SQLite)
Table: channels
Tracks active configurations for the 12 separate automated channels.

id (INTEGER, Primary Key)

channel_name (TEXT)

niche (TEXT)

tone_rules (TEXT)

youtube_credentials_path (TEXT)

Table: video_jobs
The core workflow engine table. Tracks status of every scheduled video.

id (INTEGER, Primary Key)

channel_id (INTEGER, Foreign Key to channels)

raw_topic (TEXT) — User inputs this weekly

status (TEXT: 'PENDING', 'GENERATING_TEXT', 'GENERATING_AUDIO', 'RENDERING', 'READY_TO_UPLOAD', 'COMPLETED', 'FAILED')

script (TEXT, Nullable)

title (TEXT, Nullable)

description (TEXT, Nullable)

audio_path (TEXT, Nullable)

video_output_path (TEXT, Nullable)

scheduled_time (DATETIME, Nullable)

error_log (TEXT, Nullable)

5. Module Implementation Specifications
A. Core Orchestrator (main.py)
Runs on a scheduled daily cron job. It queries video_jobs where status = 'PENDING', fetches the designated channel parameters, and pipes the output sequentially through the engines.

B. LLM Engine (core/llm_engine.py)
Sends a strict system prompt to the API demanding a structured JSON string containing video_title, youtube_description, hashtags (array), and video_script (optimized for under 140 words, zero narrative directions, just raw spoken text).

C. TTS Engine (core/tts_engine.py)
Utilizes ElevenLabs API. Must request word-level timestamps (with_timestamps=True) alongside the audio payload. Timestamps must be saved or cached locally to guide the Subtitle Burner in the video editor module.

D. Video Editor (core/video_editor.py)
Does not use external desktop video editors like CapCut. Everything is rendered via MoviePy.

Algorithm:

Loads background video from assets/backgrounds/{niche}/ dynamically.

Overlays the ElevenLabs .mp3 track.

Uses the ElevenLabs word timestamps to construct animated, center-aligned text clips (TextClip).

Applies a standard high-contrast text style (e.g., Yellow/White thick sans-serif font with a subtle dark stroke/shadow).

Exports the timeline strictly in 9:16 aspect ratio (1080x1920).

E. YouTube Uploader (core/youtube_uploader.py)
Handles Google OAuth2 tokens dynamically per channel. Sends a videos.insert request with status.privacyStatus = 'private' or status.publishAt = ISO-8601-String to execute autonomous future scheduling.

6. Rules for Code Generation
When writing code for this project, always:

Include extensive try/except blocks in every module. If one channel's render fails, it must log the error to video_jobs.error_log, set status = 'FAILED', and seamlessly continue to the next video job.

Ensure file paths are generated dynamically using Python's pathlib.

Adhere to clean, PEP 8 standard code styles.


---

