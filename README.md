# ExamRoll — Intelligent Exam Document Processor

## What It Does

ExamRoll is a web application built for college exam departments to automate the tedious process of converting attestation sheets into organized, styled Excel reports. Upload a PDF attestation sheet or an Excel roll list, and ExamRoll's AI pipeline extracts every student's roll number and subject enrollments — then generates a publication-ready, subject-wise Excel workbook in seconds.

The backend uses Groq's Llama model to classify the document type and enrich subject metadata, while robust rule-based extractors handle the actual data parsing. If the AI is unavailable, the pipeline falls back gracefully to rule-based extraction, ensuring the app is always usable. Real-time progress updates are delivered to the browser via WebSocket so users can watch each processing step live.

Every processed document is stored in a local SQLite database, giving the exam department a searchable history of all uploads with the ability to re-download any previously generated Excel file. The entire stack runs locally on Windows with two simple terminal commands — no cloud account required except for the free Groq API key.

## Features

- **PDF Attestation Sheet processing** — Extracts roll numbers and subject codes page-by-page from RDVV-format attestation PDFs
- **Excel file processing** — Auto-detects matrix format (subject codes as column headers) and flat-list format (paper codes in one column)
- **AI-powered document classification** — Identifies document type, course, semester, and exam name using Groq Llama 3.1
- **Subject name enrichment** — Merges AI-detected subject names with rule-based code detection
- **Real-time progress bar** — WebSocket-driven live updates through every processing step
- **AI Insight card** — Shows document metadata, detected subjects, and confidence score after upload
- **Customizable Excel output** — Choose header colour, font, font size, and column width before downloading
- **Two-sheet Excel output** — "Subject-wise Roll Number List" with alternating row colours and COUNTA formulas, plus a "Summary" sheet with metadata and per-subject enrollment counts
- **Job history** — Paginated table of all uploads with status badges, delete, and re-download
- **404 page** — Friendly not-found page for unknown routes
- **Health check** — `/health` endpoint for monitoring

## Tech Stack

| Layer       | Technology                                           |
|-------------|------------------------------------------------------|
| Frontend    | React 18, Vite 5, Tailwind CSS 3, React Router v6   |
| State       | TanStack Query v5, React Context                     |
| Backend     | FastAPI 0.115, Python 3.11+, Uvicorn                 |
| Database    | SQLite via SQLAlchemy 2.0 async ORM + aiosqlite      |
| AI          | Groq API — llama-3.1-8b-instant                     |
| PDF         | pdfplumber (primary) + pypdf (fallback)              |
| Excel I/O   | openpyxl                                             |
| Real-time   | WebSocket (native FastAPI)                           |
| HTTP Client | Axios + TanStack Query                               |
| Testing     | pytest 8                                             |

## Prerequisites

- Python 3.11 or higher
- Node.js 20 or higher
- A free Groq API key — get one at [console.groq.com](https://console.groq.com)

## Setup & Installation (Windows)

### 1. Clone / download the project

```powershell
# The project should already be at C:\Projects\examroll
cd C:\Projects\examroll
```

### 2. Configure environment variables

```powershell
copy .env.example .env
# Open .env in any editor and set your Groq key:
# GROQ_API_KEY=gsk_your_key_here
```

### 3. Set up the Python backend

```powershell
cd C:\Projects\examroll\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Set up the React frontend

```powershell
cd C:\Projects\examroll\frontend
npm install
```

## Running the App

Open **two terminals** and run one command in each:

**Terminal 1 — Backend**
```powershell
cd C:\Projects\examroll\backend
venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Frontend**
```powershell
cd C:\Projects\examroll\frontend
npm run dev
```

Then open **http://localhost:5173** in your browser.

| URL                          | Description                    |
|------------------------------|--------------------------------|
| http://localhost:5173        | ExamRoll web app               |
| http://localhost:8000/docs   | Interactive API documentation  |
| http://localhost:8000/health | Health check JSON              |

## Running Tests

```powershell
cd C:\Projects\examroll\backend
venv\Scripts\activate
python -m pytest tests/test_extractors.py -v
```

## Supported File Formats

| Format                        | Description                                                           |
|-------------------------------|-----------------------------------------------------------------------|
| PDF Attestation Sheets        | RDVV-format, one student per page; roll number + subject codes        |
| Excel — Matrix format         | Header row contains subject codes as columns, rows are students       |
| Excel — Flat list format      | One column holds space/comma-separated paper codes per student        |

Maximum file size: 50 MB (configurable via `MAX_FILE_SIZE_MB` in `.env`).

## API Documentation

Full interactive docs (Swagger UI) are available at **http://localhost:8000/docs** while the backend is running.

| Method | Route                              | Description                              |
|--------|------------------------------------|------------------------------------------|
| POST   | /api/v1/upload                     | Upload PDF/Excel, start processing job   |
| GET    | /api/v1/jobs                       | List jobs (supports `skip` / `limit`)    |
| GET    | /api/v1/jobs/{job_id}              | Get job status + extracted data          |
| DELETE | /api/v1/jobs/{job_id}              | Delete job + uploaded file + outputs     |
| POST   | /api/v1/export                     | Generate + download styled Excel output  |
| GET    | /api/v1/export/{job_id}/download/{file_id} | Re-download a previous output   |
| WS     | /ws/jobs/{job_id}                  | Real-time job progress (WebSocket)       |
| GET    | /health                            | Health check                             |

## Project Structure

```
examroll/
├── .env                        Runtime secrets (never commit)
├── .env.example                Safe reference copy
├── README.md
├── CLAUDE.md                   Project bible
├── PROGRESS.md                 Phase tracker
│
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py             FastAPI app factory, CORS, WebSocket
│       ├── config.py           Settings (reads .env)
│       ├── database.py         Async SQLAlchemy engine
│       ├── websocket_manager.py WebSocket broadcast manager
│       ├── models/             ORM models (Job, ExtractedData, OutputFile)
│       ├── schemas/            Pydantic request/response models
│       ├── routers/            upload.py, jobs.py, export.py
│       ├── services/
│       │   ├── ai/             Groq classifier + extractor
│       │   ├── extractors/     pdf_extractor.py, excel_extractor.py
│       │   ├── generators/     excel_generator.py
│       │   └── pipeline/       processor.py (orchestrator)
│       └── utils/              file_utils.py, subject_utils.py
│
├── frontend/
│   └── src/
│       ├── api/client.js       Axios instance + all API functions
│       ├── context/            JobContext (TanStack Query)
│       ├── hooks/              useUpload, useJobStatus, useExport
│       ├── pages/              Dashboard, Upload, JobDetail, History, NotFound
│       └── components/         layout/, upload/, preview/, customize/, common/
│
└── uploads/                    Temp uploaded + generated files (gitignored)
```

## Roadmap

| Phase | Features                                                                 |
|-------|--------------------------------------------------------------------------|
| 2     | User login + roles (JWT), per-college data isolation, PostgreSQL          |
| 3     | PDF output with college letterhead, Word document output, print layout   |
| 4     | College branding upload, hall ticket generation, seating arrangement     |
| 5     | Marks/grades extraction, report cards, email delivery, admin dashboard   |
